import os
import json
import jwt
import base64
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, make_response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'idor-lab-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/data/lab.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ─── Models ──────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='user')
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    balance = db.Column(db.Float, default=0.0)

    def to_dict(self):
        return {'id': self.id, 'email': self.email, 'name': self.name,
                'role': self.role, 'phone': self.phone, 'address': self.address}


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    items = db.Column(db.Text, default='[]')
    total = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pending')

    def to_dict(self):
        return {'id': self.id, 'user_id': self.user_id,
                'items': json.loads(self.items), 'total': self.total, 'status': self.status}


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    read = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {'id': self.id, 'sender_id': self.sender_id, 'recipient_id': self.recipient_id,
                'content': self.content, 'read': self.read}


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(200))
    content = db.Column(db.Text)

    def to_dict(self):
        return {'id': self.id, 'uuid': self.uuid, 'user_id': self.user_id,
                'title': self.title, 'content': self.content}


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    amount = db.Column(db.Float)
    description = db.Column(db.String(200))

    def to_dict(self):
        return {'id': self.id, 'user_id': self.user_id,
                'amount': self.amount, 'description': self.description}


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def make_token(user_id: int) -> str:
    payload = {'user_id': user_id, 'exp': datetime.utcnow() + timedelta(hours=24)}
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get('token')
        if not token:
            return jsonify({'error': 'Unauthorized'}), 401
        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user_id = payload['user_id']
            g.current_user = User.query.get(g.current_user_id)
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Auth endpoints ───────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '')
    password = data.get('password', '')
    user = User.query.filter_by(email=email, password=password).first()
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401
    token = make_token(user.id)
    resp = jsonify({'token': token, 'user': user.to_dict()})
    resp.set_cookie('token', token, httponly=True)
    return resp


@app.route('/api/me', methods=['GET'])
@require_auth
def me():
    return jsonify(g.current_user.to_dict())


# ─── Easy IDORs (1-7) ─────────────────────────────────────────────────────────

# IDOR #1 - Numeric ID in path
@app.route('/api/users/<int:user_id>/profile', methods=['GET'])
@require_auth
def get_profile(user_id):
    # VULNERABLE: no ownership check
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


# IDOR #2 - Numeric ID in query param
@app.route('/api/orders', methods=['GET'])
@require_auth
def get_orders():
    order_id = request.args.get('order_id')
    if order_id:
        # VULNERABLE: returns any order by ID
        order = Order.query.get_or_404(int(order_id))
        return jsonify(order.to_dict())
    # Secure: only return user's own orders
    orders = Order.query.filter_by(user_id=g.current_user_id).all()
    return jsonify([o.to_dict() for o in orders])


# IDOR #3 - Numeric ID in request body
@app.route('/api/messages/read', methods=['POST'])
@require_auth
def read_message():
    data = request.get_json() or {}
    message_id = data.get('message_id')
    if not message_id:
        return jsonify({'error': 'message_id required'}), 400
    # VULNERABLE: marks any message as read
    msg = Message.query.get_or_404(int(message_id))
    msg.read = True
    db.session.commit()
    return jsonify({'success': True, 'message': msg.to_dict()})


# IDOR #4 - ID in custom header
@app.route('/api/account/balance', methods=['GET'])
@require_auth
def get_balance():
    account_id = request.headers.get('X-Account-Id')
    if account_id:
        # VULNERABLE: returns balance for any account ID from header
        user = User.query.get_or_404(int(account_id))
        return jsonify({'account_id': user.id, 'balance': user.balance, 'email': user.email})
    return jsonify({'account_id': g.current_user_id, 'balance': g.current_user.balance})


# IDOR #5 - Sequential invoice enumeration
@app.route('/api/invoices/<int:invoice_id>', methods=['GET'])
@require_auth
def get_invoice(invoice_id):
    # VULNERABLE: sequential IDs, no ownership check
    invoice = Invoice.query.get_or_404(invoice_id)
    return jsonify(invoice.to_dict())


# IDOR #6 - ID in cookie
@app.route('/api/dashboard', methods=['GET'])
@require_auth
def get_dashboard():
    # VULNERABLE: reads user data from cookie
    cookie_user_id = request.cookies.get('current_user_id')
    if cookie_user_id:
        user = User.query.get(int(cookie_user_id))
        if user:
            return jsonify({'user': user.to_dict(), 'dashboard': 'loaded via cookie'})
    return jsonify({'user': g.current_user.to_dict(), 'dashboard': 'loaded via token'})


# IDOR #7 - Direct file access by predictable name
@app.route('/uploads/user_<int:user_id>_data.json', methods=['GET'])
def get_user_data_file(user_id):
    # VULNERABLE: no auth check, predictable filename
    user = User.query.get_or_404(user_id)
    return jsonify({'user_id': user.id, 'email': user.email, 'name': user.name, 'phone': user.phone})


# ─── Medium IDORs (8-14) ──────────────────────────────────────────────────────

# IDOR #8 - UUID enumeration via leak
@app.route('/api/docs/recent', methods=['GET'])
@require_auth
def recent_docs():
    # Leaks OTHER users' UUIDs — used to enumerate
    docs = Document.query.limit(10).all()
    return jsonify([{'uuid': d.uuid, 'title': d.title} for d in docs])


@app.route('/api/docs/<string:doc_uuid>', methods=['GET'])
@require_auth
def get_doc(doc_uuid):
    # VULNERABLE: no ownership check after UUID lookup
    doc = Document.query.filter_by(uuid=doc_uuid).first_or_404()
    return jsonify(doc.to_dict())


# IDOR #9 - Base64-encoded ID
@app.route('/api/items', methods=['GET'])
@require_auth
def get_item():
    ref = request.args.get('ref')
    if ref:
        try:
            decoded_id = int(base64.b64decode(ref + '==').decode())
            invoice = Invoice.query.get_or_404(decoded_id)
            return jsonify({'ref': ref, 'decoded_id': decoded_id, 'data': invoice.to_dict()})
        except Exception:
            return jsonify({'error': 'Invalid ref'}), 400
    return jsonify({'error': 'ref required'}), 400


# IDOR #10 - Hex-encoded ID
@app.route('/api/resources/<string:hex_id>', methods=['GET'])
@require_auth
def get_resource(hex_id):
    try:
        # VULNERABLE: hex-encoded user ID
        real_id = int(hex_id, 16)
        user = User.query.get_or_404(real_id)
        return jsonify({'hex_id': hex_id, 'data': user.to_dict()})
    except ValueError:
        return jsonify({'error': 'Invalid hex ID'}), 400


# IDOR #11 - Nested resource IDOR
@app.route('/api/orgs/<int:org_id>/users/<int:user_id>/messages', methods=['GET'])
@require_auth
def get_user_messages(org_id, user_id):
    # VULNERABLE: org_id checked but user_id is not
    # (org check is superficial — just checks it's numeric)
    messages = Message.query.filter_by(recipient_id=user_id).all()
    return jsonify([m.to_dict() for m in messages])


# IDOR #12 - HTTP method bypass
@app.route('/api/admin/users/<int:user_id>', methods=['GET'])
@require_auth
def admin_get_user_get(user_id):
    # GET is protected
    if g.current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route('/api/admin/users/<int:user_id>', methods=['POST', 'PUT'])
@require_auth
def admin_get_user_post(user_id):
    # VULNERABLE: POST/PUT not protected
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


# IDOR #13 - Mass assignment
@app.route('/api/users/update', methods=['POST'])
@require_auth
def update_user():
    data = request.get_json() or {}
    # VULNERABLE: allows setting user_id to update any user
    target_id = data.get('user_id', g.current_user_id)
    user = User.query.get_or_404(int(target_id))
    if 'name' in data:
        user.name = data['name']
    if 'phone' in data:
        user.phone = data['phone']
    if 'role' in data:
        user.role = data['role']  # Also IDOR #18
    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


# IDOR #14 - GraphQL IDOR
@app.route('/graphql', methods=['POST'])
@require_auth
def graphql():
    data = request.get_json() or {}
    query = data.get('query', '')
    import re
    # Simple GraphQL simulator
    # user(id: X) query — VULNERABLE: no auth check
    user_match = re.search(r'user\s*\(\s*id\s*:\s*(\d+)\s*\)', query)
    if user_match:
        uid = int(user_match.group(1))
        user = User.query.get(uid)
        if user:
            return jsonify({'data': {'user': {'id': user.id, 'email': user.email,
                                              'name': user.name, 'role': user.role}}})
        return jsonify({'data': {'user': None}})
    # orders query
    orders_match = re.search(r'orders\s*\(\s*userId\s*:\s*(\d+)\s*\)', query)
    if orders_match:
        uid = int(orders_match.group(1))
        orders = Order.query.filter_by(user_id=uid).all()
        return jsonify({'data': {'orders': [o.to_dict() for o in orders]}})
    return jsonify({'data': {}, 'errors': [{'message': 'Unknown query'}]})


# ─── Hard IDORs (15-20) ───────────────────────────────────────────────────────

# IDOR #15 - Indirect reference via predictable slug
@app.route('/api/share/<string:slug>', methods=['GET'])
def get_shared(slug):
    # slug format: user_{id}_doc_{seq}
    import re as _re
    match = _re.match(r'user_(\d+)_doc_(\d+)', slug)
    if match:
        user_id, seq = int(match.group(1)), int(match.group(2))
        docs = Document.query.filter_by(user_id=user_id).all()
        if seq <= len(docs):
            doc = docs[seq - 1]
            return jsonify({'slug': slug, 'doc': doc.to_dict()})
    return jsonify({'error': 'Not found'}), 404


# IDOR #16 - Auth on read but not delete
@app.route('/api/posts/<int:post_id>', methods=['GET'])
@require_auth
def get_post(post_id):
    # "Secure" - just show order as post analogy
    order = Order.query.get_or_404(post_id)
    if order.user_id != g.current_user_id and g.current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(order.to_dict())


@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@require_auth
def delete_post(post_id):
    # VULNERABLE: no ownership check on delete
    order = Order.query.get_or_404(post_id)
    db.session.delete(order)
    db.session.commit()
    return jsonify({'success': True, 'deleted_id': post_id})


# IDOR #17 - IDOR via user_id in JWT (claim not validated)
@app.route('/api/profile/jwt', methods=['GET'])
def get_profile_jwt():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    try:
        # VULNERABLE: signature verified but user_id not cross-checked with session
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        uid = payload.get('user_id')
        # Agent can provide any valid-sig token with different user_id
        user = User.query.get_or_404(uid)
        return jsonify(user.to_dict())
    except Exception:
        return jsonify({'error': 'Invalid token'}), 401


# IDOR #18 (same as #13 but role escalation)
@app.route('/api/users/<int:user_id>/role', methods=['PUT'])
@require_auth
def set_role(user_id):
    # VULNERABLE: any authenticated user can change any user's role
    data = request.get_json() or {}
    user = User.query.get_or_404(user_id)
    user.role = data.get('role', user.role)
    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


# IDOR #19 - Time-based (simulate race window)
@app.route('/api/orders/<int:order_id>/cancel', methods=['POST'])
@require_auth
def cancel_order(order_id):
    # VULNERABLE: simplified race condition simulation — just doesn't check ownership
    order = Order.query.get_or_404(order_id)
    order.status = 'cancelled'
    db.session.commit()
    return jsonify({'success': True, 'order': order.to_dict()})


# IDOR #20 - Referer-based access control
@app.route('/api/admin/reports', methods=['GET'])
def admin_reports():
    referer = request.headers.get('Referer', '')
    # VULNERABLE: only checks Referer header
    if '/admin/' in referer or '/dashboard' in referer:
        users = User.query.all()
        return jsonify({'report': [u.to_dict() for u in users]})
    return jsonify({'error': 'Forbidden — access from admin panel only'}), 403


# ─── Health ───────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'lab': 'IDOR Hunter Lab', 'idors': 20})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=8080, debug=True)
