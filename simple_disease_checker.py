import asyncio
import asyncpg
import re
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Optional import LLM disease splitter from medicine_classifier_v2
try:
    from medicine_classifier_v2 import _split_diseases_with_llm
except Exception:
    _split_diseases_with_llm = None

# ------------------------
# Regex helpers for diseases
# ------------------------

_MODIFIER_TOKENS = {
    "mãn", "mạn", "mạn tính", "cấp", "cấp tính", "quá", "phát", "quá phát",
    "bên", "trái", "phải", "ngoài", "mủ", "bên trái", "bên phải"
}

# Role-aware prefix definitions (order = priority when aggregating)
PREFIX_DEFS = [
    { 'role': 'support', 'prefix': 'hỗ trợ điều trị' },
    { 'role': 'treat', 'prefix': 'hỗ trợ và điều trị' },
    { 'role': 'treat', 'prefix': 'hỗ trợ hoặc điều trị' },
    { 'role': 'support', 'prefix': 'hỗ trợ' },
    { 'role': 'treat',   'prefix': 'điều trị' },
    { 'role': 'treat', 'prefix': 'phòng ngừa và điều trị' },
    { 'role': 'treat', 'prefix': 'dự phòng và điều trị' },
    { 'role': 'treat',   'prefix': '' },  # bare disease mention -> treat by default
]

# Domain regex library by groups (examples provided by user)
DISEASE_REGEX_LIBRARY = {
    "respiratory": {
        "diseases": [
            r"viêm\s*phổi", r"nhiễm\s*trùng\s*phổi", r"áp\s*xe\s*phổi",
            r"viêm\s*phế\s*quản", r"viêm\s*tiểu\s*phế\s*quản",
            r"hen\s*suyễn", r"suyễn", r"lao\s*phổi", r"lao",
            r"ung\s*thư\s*phổi", r"k\s*phổi", r"COPD", r"tràn\s*dịch\s*màng\s*phổi"
        ],
        "symptoms": [
            r"ho", r"ho\s*khan", r"ho\s*có\s*đờm", r"ho\s*máu",
            r"khó\s*thở", r"thở\s*gấp", r"nghẹt\s*thở",
            r"đau\s*ngực", r"tức\s*ngực", r"đờm"
        ],
        "abbreviations": [r"\bCOPD\b", r"\bTB\b"],
        "english_mixed": [r"pneumonia", r"bronchitis", r"asthma", r"tuberculosis"],
        "with_numbers": [r"COVID[-]?19", r"H\d+N\d+"],
    },
    "ent": {
        "diseases": [
            r"viêm\s*mũi", r"viêm\s*xoang", r"viêm\s*họng",
            r"viêm\s*amidan", r"viêm\s*tai", r"polyp\s*mũi"
        ],
        "symptoms": [
            r"sổ\s*mũi", r"ngạt\s*mũi", r"đau\s*họng",
            r"khàn\s*giọng", r"đau\s*tai", r"ù\s*tai"
        ],
        "english_mixed": [r"sinusitis", r"pharyngitis"],
    },
    "digestive": {
        "diseases": [
            r"viêm\s*dạ\s*dày", r"loét\s*dạ\s*dày", r"viêm\s*ruột",
            r"viêm\s*gan", r"xơ\s*gan", r"viêm\s*tụy", r"sỏi\s*mật"
        ],
        "symptoms": [
            r"đau\s*bụng", r"nôn", r"tiêu\s*chảy", r"táo\s*bón",
            r"khó\s*tiêu", r"chướng\s*bụng"
        ],
        "english_mixed": [r"gastritis", r"hepatitis"],
        "abbreviations": [r"\bGERD\b", r"\bIBS\b"],
    },
    # Global helpers
    "flexible_space": [
        r"ho\s*-*\s*khan", r"viêm\s*[-/]\s*phổi",
        r"khó\s*[/]\s*thở", r"đau\s*[-]\s*ngực"
    ],
    "syndromes": [
        r"hội\s*chứng\s+\w+", r"syndrome\s+\w+", r"sendrom\s+\w+"
    ],
    "with_numbers_global": [r"COVID[-]?19", r"H\d+N\d+", r"type\s*[12]", r"grade\s*[1-4]"]
}

# Keywords to map disease string to groups
_GROUP_KEYWORDS = {
    # "respiratory": ["phổi", "phế quản", "tiểu phế quản", "hen", "suyễn", "lao", "copd", "màng phổi"],
    # "ent": ["mũi", "xoang", "họng", "amidan", "tai", "polyp"],
    # "digestive": ["dạ dày", "daday", "ruột", "gan", "tụy", "mật", "gan"],
}

def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def _simplify_disease_core(disease: str) -> str:
    """Remove common modifiers to get a simpler core form of disease."""
    if not disease:
        return ""
    text = _normalize_spaces(disease.lower())
    # Remove multi-word modifiers first
    for phrase in sorted([t for t in _MODIFIER_TOKENS if " " in t], key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    # Remove single-word modifiers
    tokens = [t for t in text.split(" ") if t and t not in _MODIFIER_TOKENS]
    return _normalize_spaces(" ".join(tokens))

def _insert_loose_gaps_pattern(core: str, max_gap_chars: int = 30) -> str:
    """Build a regex that allows up to N arbitrary chars between words of the disease.
    Example: "ho máu" -> r"ho.{0,30}máu" to match "ho ra máu".
    """
    words = [w for w in core.split(" ") if w]
    if not words:
        return re.escape(core)
    if len(words) == 1:
        return re.escape(words[0])
    gap = rf".{{0,{max_gap_chars}}}"
    pattern = re.escape(words[0])
    for w in words[1:]:
        pattern += gap + re.escape(w)
    return pattern

def _detect_groups_for_disease(disease_name: str) -> list:
    """Heuristically map a disease string to relevant domain groups based on keywords."""
    text = (_normalize_spaces(disease_name) or "").lower()
    matched = []
    for group, kws in _GROUP_KEYWORDS.items():
        if any(kw in text for kw in kws):
            matched.append(group)
    print("matched_detect_groups_for_disease :", matched)
    return matched

def _disease_variants(disease_name: str) -> list:
    """Generate variants for disease matching: original, simplified, and loose-gap patterns.
    Also include domain library patterns if group matches."""
    base = _normalize_spaces(disease_name)
    simple = _simplify_disease_core(base)
    variants = set()
    for form in [base, simple]:
        if not form:
            continue
        variants.add(re.escape(form))
        variants.add(_insert_loose_gaps_pattern(form))
    # Hand-crafted synonyms/aliases
    synonyms = {
        "ho máu": ["ho ra máu"],
        "viêm họng mạn tính": ["viêm họng", "viêm họng mạn"],
        "v.a": ["v\\.a"],
    }
    lower = base.lower()
    for key, vals in synonyms.items():
        if key in lower:
            for v in vals:
                v_simple = _simplify_disease_core(v)
                print("v: ", v)
                print("v_simple: ", v_simple)
                variants.add(re.escape(v))
                print("escapev: ", re.escape(v))
                variants.add(_insert_loose_gaps_pattern(v_simple))
                print("insert_loose_gaps_pattern: ", _insert_loose_gaps_pattern(v_simple))
    # Include domain library patterns based on detected groups (optional signals)
    groups = _detect_groups_for_disease(base)
    print("groups: ", groups)
    for g in groups:
        lib = DISEASE_REGEX_LIBRARY.get(g, {})
        print("lib: ", lib)
        for section in ["diseases", "abbreviations", "english_mixed", "with_numbers"]:
            for pat in lib.get(section, []) or []:
                print("pat: ", pat)
                variants.add(pat)
    # Add flexible helpers (always useful)
    for pat in DISEASE_REGEX_LIBRARY.get("flexible_space", []):
        print("pat2 ", pat)
        variants.add(pat)
    for pat in DISEASE_REGEX_LIBRARY.get("with_numbers_global", []):
        print("pat3: ", pat)
        variants.add(pat)
    print("variants: ", variants)
    return list(variants)

def _build_patterns_for_one_disease(disease: str) -> list:
    """Build regex patterns for a single disease with role-aware prefixes."""
    variants = _disease_variants(disease)
    patterns = []
    for core in variants:
        for pd in PREFIX_DEFS:
            pfx = pd['prefix']
            role = pd['role']
            if pfx:
                pattern = rf"{re.escape(pfx)}.*{core}"
            else:
                pattern = rf"{core}"
            patterns.append(pattern)
    return patterns

def _build_patterns_for_diseases(disease_list: list) -> list:
    """Build final regex patterns for DB search combining all diseases."""
    patterns = []
    for disease in disease_list:
        patterns.extend(_build_patterns_for_one_disease(disease))
    return patterns

def _build_disease_pattern_entries(disease_list: list) -> list:
    """Return entries: { disease, role, prefix, pattern, compiled } with provenance."""
    entries = []
    for d in disease_list:
        variants = _disease_variants(d)
        for core in variants:
            for pd in PREFIX_DEFS:
                pfx = pd['prefix']
                role = pd['role']
                if pfx:
                    patt = rf"{re.escape(pfx)}.*{core}"
                else:
                    patt = rf"{core}"
                try:
                    entries.append({
                        'disease': d,
                        'role': role,
                        'prefix': pfx,
                        'pattern': patt,
                        'compiled': re.compile(patt, flags=re.IGNORECASE)
                    })
                except Exception:
                    continue
    print("entries: ", entries)
    return entries

def _extract_context_by_span(text: str, start: int, end: int, context_size: int = 100) -> str:
    try:
        s = max(0, start - context_size)
        e = min(len(text), end + context_size)
        snippet = text[s:e]
        if s > 0:
            snippet = "..." + snippet
        if e < len(text):
            snippet = snippet + "..."
        return snippet
    except Exception as e:
        return f"Lỗi khi trích xuất context: {e}"

async def _split_into_diseases(diagnosis_text: str) -> list:
    text = (diagnosis_text or "").strip()
    if not text:
        return []
    if _split_diseases_with_llm:
        try:
            diseases = await _split_diseases_with_llm(text)
            if diseases:
                return diseases
        except Exception:
            pass
    parts = re.split(r"[;/\\|,]+", text)
    diseases = []
    seen = set()
    for p in parts:
        s = _normalize_spaces(p)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            diseases.append(s)
    return diseases

async def check_drug_list_by_multi_diseases_ilike(diagnosis_text: str, drug_names, database_url: str = None):
    """
    1) Tách chẩn đoán thành nhiều bệnh (LLM nếu có)
    2) ILIKE theo danh sách thuốc; regex ~* theo bệnh
    3) Trả về: diagnosis_text, diseases, per-drug classification (treat/support/prevent/unrelated),
       related_diseases (theo role), và chi tiết match (id, disease, role, prefix, pattern, context, span)
    """
    diseases = await _split_into_diseases(diagnosis_text)
    if not diseases:
        return { 'diagnosis_text': diagnosis_text, 'diseases': [], 'results': [] }

    if not database_url:
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise ValueError("Cần cung cấp DATABASE_URL")

    if isinstance(drug_names, str):
        input_names = [drug_names]
    else:
        input_names = list(drug_names)
    input_names = [n for n in (n.strip() for n in input_names) if n]
    if not input_names:
        return { 'diagnosis_text': diagnosis_text, 'diseases': diseases, 'results': [] }

    all_patterns = _build_patterns_for_diseases(diseases)
    # print("all_patterns: ", all_patterns)
    combined_pattern = '|'.join(all_patterns)

    # Provenance entries to map matches to disease + role
    entries = _build_disease_pattern_entries(diseases)
    # print("entries: ", entries)

    ilike_patterns = [f"%{name}%" for name in input_names]

    query = """
    SELECT id, name, indications_longchau
    FROM drug_officially
    WHERE name ILIKE ANY($2::text[]) AND indications_longchau ~* $1
    ORDER BY name
    """
    # Fuzzy (pg_trgm) query: per input drug name, take top 3 most similar by name
    fuzzy_query = """
    SELECT id, name, indications_longchau,
           GREATEST(SIMILARITY(LOWER(name), LOWER($2)), WORD_SIMILARITY(LOWER($2), LOWER(name))) AS sim
    FROM drug_officially
    WHERE indications_longchau ~* $1
    ORDER BY sim DESC, length(name)
    LIMIT 3
    """

    try:
        conn = await asyncpg.connect(database_url)
        # Ensure pg_trgm extension for fuzzy search
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:
            pass
        rows = await conn.fetch(query, combined_pattern, ilike_patterns)

        grouped = {name: [] for name in input_names}
        grouped_ids = {name: set() for name in input_names}
        for row in rows:
            row_name_lower = (row['name'] or '').lower()
            text = row['indications_longchau'] or ''
            for input_name in input_names:
                if row_name_lower.find(input_name.lower()) != -1:
                    # Scan all entries to find matches with spans
                    disease_to_patterns = {}
                    detailed = []
                    for ent in entries:
                        m = ent['compiled'].search(text)
                        if m:
                            disease_to_patterns.setdefault(ent['disease'], []).append(ent['pattern'])
                            detailed.append({
                                'disease': ent['disease'],
                                'role': ent['role'],
                                'prefix': ent['prefix'],
                                'pattern': ent['pattern'],
                                'span': [m.start(), m.end()],
                                'context': _extract_context_by_span(text, m.start(), m.end(), context_size=100)
                            })
                    # matched_case kept for backward compat (1 if any, else None)
                    matched_case = 1 if disease_to_patterns else None
                    rec = {
                        'id': row['id'],
                        'name': row['name'],
                        'matched_case': matched_case,
                        'matched_diseases': sorted(list(disease_to_patterns.keys())),
                        'matched_patterns': detailed,
                    }
                    if row['id'] not in grouped_ids[input_name]:
                        grouped[input_name].append(rec)
                        grouped_ids[input_name].add(row['id'])

        # Fuzzy-enhanced: fetch top-3 per input drug name and merge
        for input_name in input_names:
            try:
                frows = await conn.fetch(fuzzy_query, combined_pattern, input_name)
                for row in frows:
                    if row['id'] in grouped_ids[input_name]:
                        continue
                    text = row['indications_longchau'] or ''
                    disease_to_patterns = {}
                    detailed = []
                    for ent in entries:
                        m = ent['compiled'].search(text)
                        if m:
                            disease_to_patterns.setdefault(ent['disease'], []).append(ent['pattern'])
                            detailed.append({
                                'disease': ent['disease'],
                                'role': ent['role'],
                                'prefix': ent['prefix'],
                                'pattern': ent['pattern'],
                                'span': [m.start(), m.end()],
                                'context': _extract_context_by_span(text, m.start(), m.end(), context_size=100)
                            })
                    matched_case = 1 if disease_to_patterns else None
                    rec = {
                        'id': row['id'],
                        'name': row['name'],
                        'matched_case': matched_case,
                        'matched_diseases': sorted(list(disease_to_patterns.keys())),
                        'matched_patterns': detailed,
                    }
                    grouped[input_name].append(rec)
                    grouped_ids[input_name].add(row['id'])
            except Exception:
                continue

        await conn.close()

        # Aggregate per drug with role priority: treat > support > prevent > unrelated
        role_priority = {'treat': 3, 'support': 2, 'prevent': 1}
        results_out = []
        for input_name in input_names:
            matches = grouped.get(input_name, [])
            if not matches:
                results_out.append({
                    'input_name': input_name,
                    'role': 'unrelated',
                    'related_diseases': [],
                    'matched': False,
                    'matched_count': 0,
                    'matches': []
                })
                continue
            # Determine role
            best_role = 'unrelated'
            best_score = 0
            for m in matches:
                for det in m.get('matched_patterns', []):
                    score = role_priority.get(det.get('role'), 0)
                    if score > best_score:
                        best_score = score
                        best_role = det.get('role')
            # Related diseases for the chosen role
            related = sorted(list({ det['disease'] for m in matches for det in m.get('matched_patterns', []) if det.get('role') == best_role })) if best_role != 'unrelated' else []
            results_out.append({
                'input_name': input_name,
                'role': best_role,
                'related_diseases': related,
                'matched': True,
                'matched_count': len(matches),
                'matches': matches
            })

        return { 'diagnosis_text': diagnosis_text, 'diseases': diseases, 'results': results_out }

    except Exception as e:
        print(f"Lỗi khi tìm theo multi-diseases ILIKE: {e}")
        raise

async def main():
    """Ví dụ sử dụng"""
    
    # Thay đổi thông tin kết nối database của bạn
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    # Hoặc set biến môi trường:
    # export DATABASE_URL="postgresql://username:password@localhost:5432/database_name"
    
    try:
        # Ví dụ chẩn đoán có nhiều bệnh
        diagnosis_text = "Viêm phổi, Viêm mũi mủ/ Viêm họng cấp SARS coV-2 dương tính/ Rối loạn tiêu hóa"
        drugs = ["Bilclamos", "Medrol", "Ileffexime", "cefprozil"]

        print("Tách bệnh từ chẩn đoán...")
        diseases = await _split_into_diseases(diagnosis_text)
        print("Diseases:", diseases)

        print(f"\nKiểm tra ILIKE với đa bệnh cho {len(drugs)} thuốc")
        multi = await check_drug_list_by_multi_diseases_ilike(diagnosis_text, drugs, database_url)
        print("Danh sách bệnh:", multi['diseases'])
        for s in multi['results']:
            # print('=================s: ', s)
            print(f"\n- Thuốc nhập: {s['input_name']}")
            print(f"  Có nhắc tới bệnh: {s['matched']}")
            print(f"  Bệnh khớp: {s.get('matched_diseases')}")
            print(f"  Số bản ghi match: {s['matched_count']}")
            for m in s['matches'][:5]:
                print(f"    • ID: {m['id']} | Tên: {m['name']} | Case: {m['matched_case']}")
                if m.get('matched_diseases'):
                    print(f"      - Diseases: {m['matched_diseases']}")
                if m.get('matched_patterns'):
                    print(f"      - First pattern: {m['matched_patterns'][0]}")
        
    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    # Chạy ví dụ
    asyncio.run(main())
