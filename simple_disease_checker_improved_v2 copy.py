import asyncio
import asyncpg
import re
import os
from functools import lru_cache
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Debug logging flag
DEBUG = (os.getenv("AZINSU_DEBUG", "0") == "1")

# Global connection pool and one-time pg_trgm init flag
_POOL = None
_TRGM_INIT_DONE = False

async def _get_pool(database_url: str):
    global _POOL
    if _POOL is None:
        _POOL = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
    return _POOL

async def _ensure_trgm(pool):
    global _TRGM_INIT_DONE
    if _TRGM_INIT_DONE:
        return
    async with pool.acquire() as conn:
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:
            pass
    _TRGM_INIT_DONE = True

# Optional import LLM disease splitter from medicine_classifier_v2
try:
    from medicine_classifier_v2 import _split_diseases_with_llm
except Exception:
    _split_diseases_with_llm = None

# ------------------------
# Improved Disease Variants System
# ------------------------

_MODIFIER_TOKENS = {
    "mãn", "mạn", "mạn tính", "cấp", "cấp tính", "quá", "phát", "quá phát",
    "bên", "trái", "phải", "ngoài", "mủ", "bên trái", "bên phải"
}

# New improved disease variants system
DISEASE_VARIANTS = {
    "viêm họng": {
        "main_keywords": ["viêm", "họng"],
        "variants": [
            r"viêm\s*họng", r"viêm\s*họng\s*cấp", r"viêm\s*họng\s*mạn",
            r"viêm\s*họng\s*cấp\s*tính", r"viêm\s*họng\s*mạn\s*tính",
            r"pharyngitis", r"đau\s*họng"
        ],
        "symptoms": [],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "viêm tai": {
        "main_keywords": ["viêm", "tai"],
        "variants": [
            r"viêm\s*tai", r"viêm\s*tai\s*ngoài", r"viêm\s*tai\s*giữa",
            r"viêm\s*giữa\s*tai", r"viêm\s*ngoài\s*tai", r"viêm\s*tai\s*giữa",
            r"otitis", r"đau\s*tai"
        ],
        "symptoms": [],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "viêm mũi": {
        "main_keywords": ["viêm", "mũi"],
        "variants": [
            r"viêm\s*mũi", r"viêm\s*mũi\s*dị\s*ứng", r"viêm\s*mũi\s*xoang",
            r"viêm\s*xoang", r"sinusitis", r"sổ\s*mũi"
        ],
        "symptoms": [],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "viêm phổi": {
        "main_keywords": ["viêm", "phổi"],
        "variants": [
            r"viêm\s*phổi", r"nhiễm\s*trùng\s*phổi", r"áp\s*xe\s*phổi",
            r"pneumonia", r"lao\s*phổi", r"lao"
        ],
        "symptoms": [],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "viêm dạ dày": {
        "main_keywords": ["viêm", "dạ", "dày"],
        "variants": [
            r"viêm\s*dạ\s*dày", r"viêm\s*loét\s*dạ\s*dày", r"loét\s*dạ\s*dày",
            r"gastritis", r"đau\s*dạ\s*dày"
        ],
        "symptoms": [],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "hen suyễn": {
        "main_keywords": ["hen", "suyễn"],
        "variants": [
            r"hen\s*suyễn", r"suyễn", r"asthma", r"hen\s*phế\s*quản"
        ],
        "symptoms": [],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    # Add more diseases for better coverage
    "viêm amidan": {
        "main_keywords": ["viêm", "amidan"],
        "variants": [
            r"viêm\s*amidan", r"amidan", r"tonsillitis"
        ],
        "symptoms": [r"đau\s*họng", r"nuốt\s*đau"],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "viêm xoang": {
        "main_keywords": ["viêm", "xoang"],
        "variants": [
            r"viêm\s*xoang", r"sinusitis", r"viêm\s*mũi\s*xoang"
        ],
        "symptoms": [r"đau\s*đầu", r"nghẹt\s*mũi", r"sổ\s*mũi"],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    },
    "rối loạn tiêu hóa": {
        "main_keywords": ["rối", "loạn", "tiêu", "hóa"],
        "variants": [
            r"rối\s*loạn\s*tiêu\s*hóa", r"tiêu\s*hóa", r"digestive\s*disorder"
        ],
        "symptoms": [r"đau\s*bụng", r"tiêu\s*chảy", r"táo\s*bón"],
        "role_patterns": {
            "treat": [],
            "support": []
        }
    }
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

def extract_words_from_pattern(pattern: str) -> list:
    """Extract meaningful words from regex pattern."""
    # Remove regex special characters and extract words
    clean_pattern = re.sub(r'[\\\[\](){}.*+?^$|]', ' ', pattern)
    clean_pattern = re.sub(r'\s+', ' ', clean_pattern)
    words = [word.strip() for word in clean_pattern.split() if len(word.strip()) > 1]
    return words

def find_matching_diseases(disease_name: str) -> list:
    """Find diseases that match based on keywords (at least 1 common keyword for better coverage)."""
    core = _simplify_disease_core(disease_name)
    core_words = set(core.split())
    
    matching_diseases = []
    
    for disease_key, disease_data in DISEASE_VARIANTS.items():
        main_keywords = set(disease_data["main_keywords"])
        
        # Need at least 1 common keyword (relaxed for better coverage)
        common_words = core_words.intersection(main_keywords)
        if len(common_words) >= 2:
            matching_diseases.append(disease_key)
            if DEBUG:
                print(f"Matched '{disease_name}' -> '{disease_key}' (keywords: {common_words})")
    
    return matching_diseases

def get_disease_variants(disease_name: str) -> list:
    """Get relevant variants for a disease based on keyword matching."""
    matching_diseases = find_matching_diseases(disease_name)
    print("matching_diseases: ", matching_diseases)
    
    all_variants = []
    for disease_key in matching_diseases:
        disease_data = DISEASE_VARIANTS[disease_key]
        all_variants.extend(disease_data["variants"])
        all_variants.extend(disease_data["symptoms"])
    if DEBUG:
        print("all_variants: ", all_variants)
    return list(set(all_variants))  # Remove duplicates

def _insert_loose_gaps_pattern(core: str, max_gap_chars: int = 5) -> str:
    """Build a regex that allows up to N characters between disease words (order preserved)."""
    words = [w for w in core.split(" ") if w]
    if not words:
        return re.escape(core)
    if len(words) == 1:
        return rf"\b{re.escape(words[0])}\b"
    gap = rf".{{0,{max_gap_chars}}}"
    pattern = rf"\b{re.escape(words[0])}\b"
    for w in words[1:]:
        pattern += gap + rf"\b{re.escape(w)}\b"
    return pattern

def _disease_variants(disease_name: str) -> list:
    """Generate variants for disease matching using improved system."""
    base = _normalize_spaces(disease_name)
    print("disease_name: ", disease_name, "-> base: ", base)
    simple = _simplify_disease_core(base)
    print("  -> simple: ", simple)
    variants = set()
    
    # Add original and simplified forms
    for form in [base, simple]:
        print("  form: ", form)
        if not form:
            continue
        variants.add(re.escape(form))
        # variants.add(_insert_loose_gaps_pattern(form))
    
    # Add variants from DISEASE_VARIANTS system
    disease_variants = get_disease_variants(disease_name)
    variants.update(disease_variants)
    print("  disease_variants: ", disease_variants)
    print("  _disease_variants: ", variants)
    if DEBUG:
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
                pattern = rf"{re.escape(pfx)}.{{0,7}}{core}"
            else:
                pattern = rf"{core}"
            patterns.append(pattern)
    return patterns

def _normalize_diseases_key(disease_list: list) -> tuple:
    return tuple(sorted([_normalize_spaces(d).lower() for d in (disease_list or []) if _normalize_spaces(d)]))

# @lru_cache(maxsize=256)
def _cached_patterns(diseases_key: tuple) -> list:
    patterns = []
    for disease in diseases_key:
        patterns.extend(_build_patterns_for_one_disease(disease))
    # print("INPUT of _cached_patterns: ", diseases_key)
    # print("OUTPUT of _cached_patterns: ", patterns)
    return patterns

def _build_patterns_for_diseases(disease_list: list) -> list:
    """Build final regex patterns for DB search combining all diseases."""
    diseases_key = _normalize_diseases_key(disease_list)
    # print("INPUT of _build_patterns_for_diseases: ", disease_list)
    # print("OUTPUT of _normalize_diseases_key: ", diseases_key)
    # print("OUTPUT of _build_patterns_for_diseases (normalized key): ", _cached_patterns(diseases_key))
    return _cached_patterns(diseases_key)

# @lru_cache(maxsize=256)
def _cached_pattern_entries(diseases_key: tuple) -> list:
    entries = []
    for d in diseases_key:
        variants = _disease_variants(d)
        for core in variants:
            for pd in PREFIX_DEFS:
                pfx = pd['prefix']
                role = pd['role']
                if pfx:
                    patt = rf"{re.escape(pfx)}.{{0,7}}{core}"
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
    return entries

def _build_disease_pattern_entries(disease_list: list) -> list:
    """Return entries: { disease, role, prefix, pattern, compiled } with provenance."""
    diseases_key = _normalize_diseases_key(disease_list)
    return _cached_pattern_entries(diseases_key)

def _extract_context_by_span(text: str, start: int, end: int, context_size: int = 10) -> str:
    try:
        s = max(0, start - context_size)
        e = min(len(text), end + context_size)
        snippet = text[s:e]
        if s > 0:
            snippet = "..." + snippet
        if e < len(text):
            snippet = snippet + "..."
        # print("text: ", text)
        # print("start: ", start)
        # print("end: ", end)
        # print("context_size: ", context_size)
        # print("snippet: ", snippet)
        return snippet
    except Exception as e:
        return f"Lỗi khi trích xuất context: {e}"

def _unique_preserve_order(items: list) -> list:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

def _build_indications_snippets(detailed: list, delimiter: str = " ...... ", max_snippets: int = 8, max_chars: int = 800) -> str:
    # Deduplicate contexts, keep order
    contexts = [d.get('context', '') for d in detailed if d.get('context')]
    contexts = _unique_preserve_order(contexts)
    # Limit number of snippets
    contexts = contexts[:max_snippets]
    # Join with delimiter
    joined = delimiter.join(contexts)
    # Enforce max length
    if len(joined) > max_chars:
        joined = joined[:max_chars - 3] + '...'
    # Normalize whitespace a bit
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

async def _llm_validate_drug_matches(original_drug: str, matched_drugs: list, diagnosis_text: str) -> list:
    """
    Sử dụng LLM để kiểm tra xem các thuốc matched có thực sự phù hợp với thuốc gốc không.
    
    Args:
        original_drug: Tên thuốc gốc cần tìm
        matched_drugs: Danh sách thuốc đã match từ DB
        diagnosis_text: Chẩn đoán để LLM hiểu context
    
    Returns:
        List thuốc được LLM xác nhận là phù hợp
    """
    if not matched_drugs or len(matched_drugs) <= 1:
        return matched_drugs
    
    try:
        # Import OpenAI client
        import openai
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Tạo prompt cho LLM
        prompt = f"""
Bạn là chuyên gia dược học. Hãy phân tích xem các thuốc sau có phù hợp với thuốc gốc "{original_drug}" không.

THUỐC GỐC CẦN TÌM: {original_drug}
CHẨN ĐOÁN: {diagnosis_text}

DANH SÁCH THUỐC ĐÃ TÌM THẤY:
{chr(10).join([f"{i+1}. {drug['name']}" for i, drug in enumerate(matched_drugs)])}

Hãy phân tích từng thuốc và trả về kết quả theo format JSON:
{{
    "analysis": [
        {{
            "drug_name": "tên thuốc",
            "is_suitable": true/false,
            "confidence": "high/medium/low",
            "reason": "lý do tại sao phù hợp hoặc không phù hợp"
        }}
    ]
}}

QUY TẮC:
- Nếu thuốc có tên giống hệt hoặc rất giống với thuốc gốc → is_suitable: true
- Nếu thuốc có tên giống nhưng khác dạng bào chế (viên, siro, tiêm, etc.) → is_suitable: false
- Nếu thuốc có tên giống nhưng khác hàm lượng → is_suitable: false  
- Nếu thuốc có tên giống nhưng khác nhà sản xuất → is_suitable: true (nếu cùng hoạt chất)
- Nếu không chắc chắn → is_suitable: true, confidence: "low"

Chỉ trả về JSON, không giải thích thêm.
"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Bạn là chuyên gia dược học với kiến thức sâu về thuốc và dạng bào chế. Trả về kết quả dưới dạng JSON hợp lệ."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"}
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        import json
        try:
            result = json.loads(result_text)
            validated_drugs = []
            
            for analysis in result.get("analysis", []):
                drug_name = analysis.get("drug_name", "")
                is_suitable = analysis.get("is_suitable", True)
                confidence = analysis.get("confidence", "medium")
                
                # Tìm thuốc tương ứng trong danh sách gốc
                for drug in matched_drugs:
                    if drug["name"] == drug_name:
                        if is_suitable or confidence == "low":
                            # Thêm thông tin LLM vào drug object
                            drug["llm_validation"] = {
                                "is_suitable": is_suitable,
                                "confidence": confidence,
                                "reason": analysis.get("reason", "")
                            }
                            validated_drugs.append(drug)
                        break
            
            if DEBUG:
                print(f"LLM validation for '{original_drug}': {len(validated_drugs)}/{len(matched_drugs)} drugs validated")
            return validated_drugs
            
        except json.JSONDecodeError as e:
            if DEBUG:
                print(f"LLM response parsing error: {e}")
            return matched_drugs  # Fallback to original list
            
    except Exception as e:
        if DEBUG:
            print(f"LLM validation error: {e}")
        return matched_drugs  # Fallback to original list

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

async def check_drug_list_by_multi_diseases_ilike(diagnosis_text: str, drug_names, database_url: str = None, use_llm_filter: bool = False, pre_split_diseases: list = None):
    """
    Improved version with better disease matching and optional LLM validation:
    1) Tách chẩn đoán thành nhiều bệnh (LLM nếu có)
    2) ILIKE theo danh sách thuốc; regex ~* theo bệnh với improved matching
    3) [OPTIONAL] LLM validation để lọc thuốc có tên giống nhưng khác loại/dạng bào chế
    4) Trả về: diagnosis_text, diseases, per-drug classification (treat/support/prevent/unrelated),
       related_diseases (theo role), và chi tiết match (id, disease, role, prefix, pattern, context, span)
    
    Args:
        diagnosis_text: Chẩn đoán của bác sĩ
        drug_names: Danh sách tên thuốc cần kiểm tra
        database_url: URL kết nối database
        use_llm_filter: Bật/tắt LLM validation để lọc thuốc phù hợp
    """
    if pre_split_diseases is None:
        print("Không tồn tại pre_split_diseases, tách từ diagnosis_text...")
        diseases = await _split_into_diseases(diagnosis_text)
    else:
        print("Sử dụng pre_split_diseases đã cung cấp...")
        diseases = pre_split_diseases
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
    # print("Built patterns for diseases:", all_patterns)
    combined_pattern = '|'.join(all_patterns)
    
    # print("Combined regex pattern:", (combined_pattern))
    # combined_pattern = 'hỗ\ trợ\ điều\ trị.{0,7}viêm\ họng\ cấp'

    # Provenance entries to map matches to disease + role
    entries = _build_disease_pattern_entries(diseases)
    # print("Pattern entries for provenance:", entries)

    ilike_patterns = [f"%{name}%" for name in input_names]

    # SQL query: match drug name ILIKE and indications ~* disease patterns, ordered by name: to group similar names together 
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
        pool = await _get_pool(database_url)
        await _ensure_trgm(pool)
        async with pool.acquire() as conn:
            time_start = time.time()
            rows = await conn.fetch(query, combined_pattern, ilike_patterns)
            # rows = [{'id': 1, 'name': 'xxxxx', 'indications_longchau': 'Thuốc này dùng để điều trị viêm họng và viêm xong'}]
            # print("rows: ", rows)
            time_end = time.time()
            print(f"Time taken for ILIKE query: {time_end - time_start} seconds")

            grouped = {name: [] for name in input_names}
            grouped_ids = {name: set() for name in input_names}
            for row in rows:
                row_name_lower = (row['name'] or '').lower()
                print("row_name_lower: ", row_name_lower)
                text = row['indications_longchau'] or ''
                # text = "Thuốc này dùng để điều trị viêm họng và viêm xong"
                print("text: ", text)
                for input_name in input_names:
                    print("  input_name: ", input_name)
                    if row_name_lower.find(input_name.lower()) != -1:
                        # Scan all entries to find matches with spans
                        disease_to_patterns = {}
                        detailed = []
                        for ent in entries:
                            for m in ent['compiled'].finditer(text):
                                print("======mmmmm: ", m)
                                disease_to_patterns.setdefault(ent['disease'], []).append(ent['pattern'])
                                detailed.append({
                                    'disease': ent['disease'],
                                    'role': ent['role'],
                                    'prefix': ent['prefix'],
                                    'pattern': ent['pattern'],
                                    'span': [m.start(), m.end()],
                                    'context': _extract_context_by_span(text, m.start(), m.end(), context_size=10)
                                })
                        # matched_case kept for backward compat (1 if any, else None)
                        matched_case = 1 if disease_to_patterns else None
                        # Combine contexts as requested format (concatenate snippets with limit)
                        indications_snippets = _build_indications_snippets(detailed, delimiter=" ...... ", max_snippets=8, max_chars=800)
                        rec = {
                            'id': row['id'],
                            'name': row['name'],
                            'matched_case': matched_case,
                            'matched_diseases': sorted(list(disease_to_patterns.keys())),
                            'matched_patterns': detailed,
                            'indications_snippets': indications_snippets,
                        }
                        if row['id'] not in grouped_ids[input_name]:
                            grouped[input_name].append(rec)
                            grouped_ids[input_name].add(row['id'])

            # Fuzzy-enhanced: fetch top-3 per input drug name and merge (in parallel)
            async def _fetch_fuzzy(one_name: str):
                try:
                    return one_name, await conn.fetch(fuzzy_query, combined_pattern, one_name)
                except Exception:
                    return one_name, []
            time_start = time.time()
            tasks = [asyncio.create_task(_fetch_fuzzy(input_name)) for input_name in input_names]
            fuzzy_results = await asyncio.gather(*tasks)
            # print("fuzzy_results: ", fuzzy_results)
            time_end = time.time()
            print(f"Time taken for ALLLLLL fuzzy query: {time_end - time_start} seconds")
            for input_name, frows in fuzzy_results:
                for row in frows:
                    if row['id'] in grouped_ids[input_name]:
                        continue
                    text = row['indications_longchau'] or ''
                    disease_to_patterns = {}
                    detailed = []
                    for ent in entries:
                        for m in ent['compiled'].finditer(text):
                            disease_to_patterns.setdefault(ent['disease'], []).append(ent['pattern'])
                            detailed.append({
                                'disease': ent['disease'],
                                'role': ent['role'],
                                'prefix': ent['prefix'],
                                'pattern': ent['pattern'],
                                'span': [m.start(), m.end()],
                                'context': _extract_context_by_span(text, m.start(), m.end(), context_size=10)
                            })
                    matched_case = 1 if disease_to_patterns else None
                    indications_snippets = _build_indications_snippets(detailed, delimiter=" ...... ", max_snippets=8, max_chars=800)
                    rec = {
                        'id': row['id'],
                        'name': row['name'],
                        'matched_case': matched_case,
                        'matched_diseases': sorted(list(disease_to_patterns.keys())),
                        'matched_patterns': detailed,
                        'indications_snippets': indications_snippets,
                    }
                    grouped[input_name].append(rec)
                    grouped_ids[input_name].add(row['id'])

        # LLM validation step (if enabled)
        if use_llm_filter:
            print("🔍 Applying LLM validation to filter drug matches...")
            for input_name in input_names:
                if grouped[input_name]:
                    original_matches = grouped[input_name].copy()
                    validated_matches = await _llm_validate_drug_matches(
                        input_name, 
                        original_matches, 
                        diagnosis_text
                    )
                    grouped[input_name] = validated_matches
                    print(f"  {input_name}: {len(validated_matches)}/{len(original_matches)} drugs passed LLM validation")

        # pool-managed connections auto-closed by context manager

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
    """Ví dụ sử dụng với improved system và LLM validation"""
    
    # Thay đổi thông tin kết nối database của bạn
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    try:
        time_start = time.time()
        # Ví dụ chẩn đoán có nhiều bệnh
        # diagnosis_text = "Viêm chít hẹp ống tai ngoài bên trái; V.A quá phát, Viêm mũi mủ/ Viêm họng cấp SARS coV-2 dương tính/ Rối loạn tiêu hóa"
        diagnosis_text = "Viêm họng cấp"
        drugs = ["Bilclamos", "Medrol", "Ileffexime", "cefprozil"]

        print("Tách bệnh từ chẩn đoán...")
        time_start = time.time()
        diseases = await _split_into_diseases(diagnosis_text)
        print("Diseases:", diseases)
        time_end = time.time()
        print(f"Time taken for split diseases: {time_end - time_start} seconds")

        print(f"\n{'='*60}")
        print("KIỂM TRA KHÔNG CÓ LLM VALIDATION")
        print(f"{'='*60}")
        time_start = time.time()
        multi = await check_drug_list_by_multi_diseases_ilike(diagnosis_text, drugs, database_url, use_llm_filter=False)
        time_end = time.time()
        print(f"\n{'='*60}")
        print("FULL KẾT QUẢ: ", multi)
        print(f"\n{'='*60}")
        print(f"Time taken for check drug list by multi diseases ilike: {time_end - time_start} seconds")
        print("Danh sách bệnh:", multi['diseases'])
        for s in multi['results']:
            print(f"\n- Thuốc nhập: {s['input_name']}")
            print(f"  Có nhắc tới bệnh: {s['matched']}")
            print(f"  Bệnh khớp: {s.get('matched_diseases')}")
            print(f"  Số bản ghi match: {s['matched_count']}")
            for m in s['matches'][:3]:
                print(f"    • ID: {m['id']} | Tên: {m['name']} | Case: {m['matched_case']}")
                if m.get('matched_diseases'):
                    print(f"      - Diseases: {m['matched_diseases']}")

        # print(f"\n{'='*60}")
        # print(f"{'='*60}")
        # time_start = time.time()
        # multi_with_llm = await check_drug_list_by_multi_diseases_ilike(diagnosis_text, drugs, database_url, use_llm_filter=True)
        # time_end = time.time()
        # # print(f"Time taken for check drug list by multi diseases ilike: {time_end - time_start} seconds")
        # print("Danh sách bệnh:", multi_with_llm['diseases'])
        # for s in multi_with_llm['results']:
        #     print(f"\n- Thuốc nhập: {s['input_name']}")
        #     print(f"  Có nhắc tới bệnh: {s['matched']}")
        #     print(f"  Bệnh khớp: {s.get('matched_diseases')}")
        #     print(f"  Số bản ghi match: {s['matched_count']}")
        #     for m in s['matches'][:3]:
        #         print(f"    • ID: {m['id']} | Tên: {m['name']} | Case: {m['matched_case']}")
        #         if m.get('matched_diseases'):
        #             print(f"      - Diseases: {m['matched_diseases']}")
        #         if m.get('llm_validation'):
        #             llm_info = m['llm_validation']
        #             print(f"      - LLM: {llm_info['confidence']} confidence, {llm_info['reason']}")
        
        # time_end = time.time()
        # print(f"Time ALL: {time_end - time_start} seconds")
    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    # Chạy ví dụ
    asyncio.run(main())
