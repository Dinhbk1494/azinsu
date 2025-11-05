import asyncio
import asyncpg
import re
import os
from functools import lru_cache
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# ===========================================
# CONFIGURATION VARIABLES - Dễ tùy chỉnh
# ===========================================

# Debug logging flag
DEBUG = (os.getenv("AZINSU_DEBUG", "0") == "1")

# Search parameters
FUZZY_TOP_K = 5  # Top K thuốc từ fuzzy search
CONTEXT_WORDS = 10  # Số từ context mỗi bên khi extract
MAX_SNIPPETS = 8  # Số snippet tối đa
MAX_CHARS = 800  # Độ dài snippet tối đa

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
# Disease Pattern System
# ------------------------

_MODIFIER_TOKENS = {
    "mãn", "mạn", "mạn tính", "cấp", "cấp tính", "quá", "phát", "quá phát",
    "bên", "trái", "phải", "ngoài", "mủ", "bên trái", "bên phải"
}

# Disease variants system
DISEASE_VARIANTS = {
    "viêm họng": {
        "main_keywords": ["viêm", "họng"],
        "variants": [
            r"viêm\s*họng",r"đau\s*họng"
        ],
        "symptoms": [],
    },
    "viêm tai": {
        "main_keywords": ["viêm", "tai"],
        "variants": [
            r"viêm\s*tai", r"đau\s*tai"
        ],
        "symptoms": [],
    },
    "viêm mũi": {
        "main_keywords": ["viêm", "mũi"],
        "variants": [
            r"viêm\s*mũi", r"viêm\s*xoang", r"nghẹt\s*mũi"
        ],
        "symptoms": [],
    },
    "viêm phổi": {
        "main_keywords": ["viêm", "phổi"],
        "variants": [
            r"viêm\s*phổi", r"nhiễm\s*trùng\s*phổi", r"áp\s*xe\s*phổi",
            r"pneumonia", r"lao\s*phổi", r"lao"
        ],
        "symptoms": [],
    },
    "viêm dạ dày": {
        "main_keywords": ["viêm", "dạ", "dày"],
        "variants": [
            r"(viêm|loét|đau) (\s*dạ\s*dày|\s*bao\s*tử)"
        ],
        "symptoms": [],
    },
    "hen suyễn": {
        "main_keywords": ["hen", "suyễn"],
        "variants": [
            r"suyễn", r"asthma", r"hen"
        ],
        "symptoms": [],
    },
    "viêm amidan": {
        "main_keywords": ["viêm", "amidan"],
        "variants": [
            r"amidan"
        ],
        "symptoms": [r"đau\s*họng", r"nuốt\s*đau"],
    },
    "viêm xoang": {
        "main_keywords": ["viêm", "xoang"],
        "variants": [
            r"viêm\s*(xoang|mũi xoang)"
        ],
        "symptoms": [],
    },
    "rối loạn tiêu hóa": {
        "main_keywords": ["rối", "loạn", "tiêu", "hóa"],
        "variants": [
            r"tiêu\s*hóa"
        ],
        "symptoms": [r"đau\s*bụng", r"tiêu\s*chảy", r"táo\s*bón"],
    }
}

# ===========================================
# TREATMENT PATTERN DEFINITIONS - Theo yêu cầu mới
# ===========================================

# Main drug patterns (điều trị) - LOẠI TRỪ "hỗ trợ" để tránh nhầm lẫn
MAIN_DRUG_PATTERNS = [
    r"(?<!hỗ trợ )(?<!phòng ngừa )(?<!đề phòng )(điều\s*trị|chữa\s*trị|trị\s*liệu)",
]

# Secondary drug patterns (hỗ trợ) - LOẠI TRỪ "điều trị" để tránh nhầm lẫn  
SECONDARY_DRUG_PATTERNS = [
    r"(hỗ\s*trợ|phòng\s*ngừa|đề\s*phòng)(?!và điều trị)(?!hoặc điều trị)",
    r"hỗ\s*trợ điều\s*trị",  # "hỗ trợ điều trị" - vẫn là secondary
    r"(giúp\s*giảm|làm\s*giảm)(?!và điều trị)(?!hoặc điều trị)",
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

def find_matching_diseases(disease_name: str) -> list:
    """Find diseases that match based on keywords."""
    core = _simplify_disease_core(disease_name)
    core_words = set(core.split())
    
    matching_diseases = []
    
    for disease_key, disease_data in DISEASE_VARIANTS.items():
        main_keywords = set(disease_data["main_keywords"])
        
        # Need at least 2 common keywords for better precision
        common_words = core_words.intersection(main_keywords)
        if len(common_words) >= 2:
            matching_diseases.append(disease_key)
            if DEBUG:
                print(f"Matched '{disease_name}' -> '{disease_key}' (keywords: {common_words})")
    
    return matching_diseases

def get_disease_variants(disease_name: str) -> list:
    """Get relevant variants for a disease based on keyword matching."""
    matching_diseases = find_matching_diseases(disease_name)
    
    all_variants = []
    for disease_key in matching_diseases:
        disease_data = DISEASE_VARIANTS[disease_key]
        all_variants.extend(disease_data["variants"])
        all_variants.extend(disease_data["symptoms"])
    
    if DEBUG:
        print(f"Disease '{disease_name}' -> variants: {all_variants}")
    
    return list(set(all_variants))  # Remove duplicates

def _disease_variants(disease_name: str) -> list:
    """Generate variants for disease matching."""
    base = _normalize_spaces(disease_name)
    simple = _simplify_disease_core(base)
    variants = set()
    
    # Add original and simplified forms
    for form in [base, simple]:
        if not form:
            continue
        variants.add(re.escape(form))
    
    # Add variants from DISEASE_VARIANTS system
    disease_variants = get_disease_variants(disease_name)
    variants.update(disease_variants)
    
    if DEBUG:
        print(f"Final variants for '{disease_name}': {variants}")
    
    return list(variants)

def build_treatment_patterns(diseases: list) -> dict:
    """
    Tạo patterns theo yêu cầu: (điều trị|hỗ trợ|...).*(disease variants)
    Returns: {'main': [...], 'secondary': [...]}
    """
    # Get all disease variants
    all_disease_variants = []
    for disease in diseases:
        variants = _disease_variants(disease)
        print(f"Variants for disease '{disease}': {variants}")
        all_disease_variants.extend(variants)
    
    # Remove duplicates
    all_disease_variants = list(set(all_disease_variants))
    print(f"All disease variants combined: {all_disease_variants}")
    
    # Combine disease variants into one pattern
    disease_pattern = f"(?:{'|'.join(all_disease_variants)})"
    
    patterns = {
        'main': [],
        'secondary': []
    }
    
    # Build main drug patterns (điều trị)
    for prefix_pattern in MAIN_DRUG_PATTERNS:
        pattern = f"{prefix_pattern}.*?{disease_pattern}"
        patterns['main'].append({
            'pattern': pattern,
            'compiled': re.compile(pattern, re.IGNORECASE | re.DOTALL),
            'type': 'main_drug',
            'prefix_pattern': prefix_pattern
        })
    
    # Build secondary drug patterns (hỗ trợ)
    for prefix_pattern in SECONDARY_DRUG_PATTERNS:
        pattern = f"{prefix_pattern}.*?{disease_pattern}"
        patterns['secondary'].append({
            'pattern': pattern,
            'compiled': re.compile(pattern, re.IGNORECASE | re.DOTALL),
            'type': 'secondary_drug', 
            'prefix_pattern': prefix_pattern
        })
    
    if DEBUG:
        print(f"Built {len(patterns['main'])} main patterns and {len(patterns['secondary'])} secondary patterns")
    
    return patterns

def extract_context_by_words(text: str, start: int, end: int, context_words: int = CONTEXT_WORDS) -> str:
    """Extract context around match with specified number of words on each side."""
    try:
        # Find word boundaries
        words_before = text[:start].split()
        words_after = text[end:].split()
        matched_text = text[start:end]
        
        # Take last N words before and first N words after
        context_before = ' '.join(words_before[-context_words:]) if words_before else ''
        context_after = ' '.join(words_after[:context_words]) if words_after else ''
        
        # Build context
        context_parts = []
        if context_before:
            context_parts.append('...' + context_before if len(words_before) > context_words else context_before)
        context_parts.append(f"[{matched_text}]")  # Highlight matched text
        if context_after:
            context_parts.append(context_after + '...' if len(words_after) > context_words else context_after)
        
        return ' '.join(context_parts)
    except Exception as e:
        return f"Lỗi khi trích xuất context: {e}"

async def _split_into_diseases(diagnosis_text: str) -> list:
    """Split diagnosis text into individual diseases."""
    text = (diagnosis_text or "").strip()
    if not text:
        return []
    
    # Try LLM splitting first if available
    if _split_diseases_with_llm:
        try:
            diseases = await _split_diseases_with_llm(text)
            if diseases:
                return diseases
        except Exception:
            pass
    
    # Fallback to simple splitting
    parts = re.split(r"[;/\\|,]+", text)
    diseases = []
    seen = set()
    for p in parts:
        s = _normalize_spaces(p)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            diseases.append(s)
    
    return diseases

async def _llm_validate_drug_matches(original_drug: str, matched_drugs: list, diagnosis_text: str) -> list:
    """Use LLM to validate if matched drugs are actually suitable."""
    if not matched_drugs or len(matched_drugs) <= 1:
        return matched_drugs
    
    try:
        import openai
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        prompt = f"""
Bạn là chuyên gia dược học. Hãy phân tích xem các thuốc sau có phù hợp với thuốc gốc "{original_drug}" không.

THUỐC GỐC CẦN TÌM: {original_drug}
CHẨN ĐOÁN: {diagnosis_text}

DANH SÁCH THUỐC ĐÃ TÌM THẤY:
{chr(10).join([f"{i+1}. {drug['name']}" for i, drug in enumerate(matched_drugs)])}

Trả về JSON format:
{{
    "analysis": [
        {{
            "drug_name": "tên thuốc",
            "is_suitable": true/false,
            "confidence": "high/medium/low",
            "reason": "lý do"
        }}
    ]
}}

QUY TẮC:
- Tên giống hệt hoặc rất giống → is_suitable: true
- Khác dạng bào chế (viên/siro/tiêm) → is_suitable: false
- Khác hàm lượng → is_suitable: false  
- Khác nhà sản xuất nhưng cùng hoạt chất → is_suitable: true
- Không chắc chắn → is_suitable: true, confidence: "low"
"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Bạn là chuyên gia dược học. Trả về JSON hợp lệ."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"}
        )
        
        result_text = response.choices[0].message.content.strip()
        
        import json
        try:
            result = json.loads(result_text)
            validated_drugs = []
            
            for analysis in result.get("analysis", []):
                drug_name = analysis.get("drug_name", "")
                is_suitable = analysis.get("is_suitable", True)
                confidence = analysis.get("confidence", "medium")
                
                for drug in matched_drugs:
                    if drug["name"] == drug_name:
                        if is_suitable or confidence == "low":
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
            return matched_drugs
            
    except Exception as e:
        if DEBUG:
            print(f"LLM validation error: {e}")
        return matched_drugs

async def check_drug_treatment_classification(
    diagnosis_text: str, 
    drug_names, 
    database_url: str = None, 
    use_llm_filter: bool = False, 
    pre_split_diseases: list = None,
    top_k: int = FUZZY_TOP_K,
    context_words: int = CONTEXT_WORDS
):
    """
    Main function theo yêu cầu mới:
    1. Tách bệnh và tạo variants
    2. Tìm thuốc trong DB (ILIKE + fuzzy)
    3. Optional LLM validation
    4. Match với treatment patterns (main/secondary drug)
    5. Return format theo yêu cầu
    """
    
    # Step 1: Split diseases
    if pre_split_diseases is None:
        if DEBUG:
            print("Splitting diseases from diagnosis_text...")
        diseases = await _split_into_diseases(diagnosis_text)
        print(f"Identified diseases: {diseases}")
    else:
        if DEBUG:
            print("Using pre-split diseases...")
        diseases = pre_split_diseases
    
    if not diseases:
        return {
            'diagnosis_text': diagnosis_text,
            'diseases': [],
            'disease_variants': {},
            'results': {}
        }

    # Step 1a: Build treatment patterns
    if DEBUG:
        print(f"Building treatment patterns for diseases: {diseases}")
    print(f"Building treatment patterns for diseases: {diseases}")
    treatment_patterns = build_treatment_patterns(diseases)
    print(f"Built {len(treatment_patterns['main'])} main patterns and {len(treatment_patterns['secondary'])} secondary patterns")
    
    # Prepare disease variants info for output
    disease_variants = {}
    for disease in diseases:
        variants = _disease_variants(disease)
        disease_variants[disease] = variants
    print(f"Disease variants: {disease_variants}")
    # Step 2: Prepare drug names
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
        return {
            'diagnosis_text': diagnosis_text,
            'diseases': diseases, 
            'disease_variants': disease_variants,
            'results': {}
        }

    # Step 2 & 3: Search drugs in database
    all_patterns = []
    for pattern_list in [treatment_patterns['main'], treatment_patterns['secondary']]:
        all_patterns.extend([p['pattern'] for p in pattern_list])
    
    combined_pattern = '|'.join(all_patterns)
    print("=== Combined regex pattern for DB search:", combined_pattern)
    ilike_patterns = [f"%{name}%" for name in input_names]
    print("=== ILIKE patterns for DB search:", ilike_patterns)

    # SQL queries
    ilike_query = """
    SELECT id, name, indications_longchau
    FROM drug_officially
    WHERE name ILIKE ANY($1::text[]) 
    AND indications_longchau is NOT NULL
    AND indications_longchau <> ''
    ORDER BY name
    LIMIT 5
    """
    
    fuzzy_query = f"""
    SELECT id, name, indications_longchau,
           GREATEST(SIMILARITY(LOWER(name), LOWER($1)), WORD_SIMILARITY(LOWER($1), LOWER(name))) AS sim
    FROM drug_officially
    WHERE indications_longchau is NOT NULL
    AND indications_longchau <> ''
    ORDER BY sim DESC, length(name)
    LIMIT {top_k}
    """

    try:
        pool = await _get_pool(database_url)
        await _ensure_trgm(pool)
        
        async with pool.acquire() as conn:
            # ILIKE search
            if DEBUG:
                print("Executing ILIKE search...")
            start_time = time.time()
            ilike_rows = await conn.fetch(ilike_query, ilike_patterns)
            if DEBUG:
                print(f"ILIKE search took {time.time() - start_time:.2f}s, found {len(ilike_rows)} rows")

            # Group ILIKE results by input drug name
            grouped = {name: [] for name in input_names}
            grouped_ids = {name: set() for name in input_names}
            
            for row in ilike_rows:
                row_name_lower = (row['name'] or '').lower()
                for input_name in input_names:
                    if input_name.lower() in row_name_lower:
                        if row['id'] not in grouped_ids[input_name]:
                            grouped[input_name].append(dict(row))
                            grouped_ids[input_name].add(row['id'])

            # Fuzzy search for each drug
            if DEBUG:
                print("Executing fuzzy searches...")
            start_time = time.time()
            async def _fetch_fuzzy(drug_name: str):
                try:
                    return drug_name, await conn.fetch(fuzzy_query, drug_name)
                except Exception:
                    return drug_name, []

            tasks = [asyncio.create_task(_fetch_fuzzy(name)) for name in input_names]
            fuzzy_results = await asyncio.gather(*tasks)
            
            if DEBUG:
                print(f"Fuzzy search took {time.time() - start_time:.2f}s")

            # Merge fuzzy results
            for input_name, frows in fuzzy_results:
                for row in frows:
                    if row['id'] not in grouped_ids[input_name]:
                        grouped[input_name].append(dict(row))
                        grouped_ids[input_name].add(row['id'])
        # Step 3: Optional LLM validation
        if use_llm_filter:
            if DEBUG:
                print("🔍 Applying LLM validation...")
            for input_name in input_names:
                if grouped[input_name]:
                    original_count = len(grouped[input_name])
                    validated = await _llm_validate_drug_matches(
                        input_name, 
                        grouped[input_name], 
                        diagnosis_text
                    )
                    grouped[input_name] = validated
                    if DEBUG:
                        print(f"  {input_name}: {len(validated)}/{original_count} drugs passed LLM validation")

        # Step 4: Pattern matching and classification
        results = {}
        
        for input_name in input_names:
            matches = grouped.get(input_name, [])
            
            if not matches:
                results[input_name] = {
                    'match_status': False,
                    'regex_matches': [],
                    'category': 'unrelated',
                    'text_matches': [],
                    'matched_diseases': [],
                    'total_drugs_found': 0
                }
                continue

            # Analyze each drug's indications
            drug_results = []
            all_regex_matches = set()
            matched_diseases = set()
            
            for drug in matches:
                indications = drug.get('indications_longchau', '') or ''
                drug_matches = []
                drug_category = 'unrelated'
                
                # Check main drug patterns first (higher priority)
                for pattern_info in treatment_patterns['main']:
                    for match in pattern_info['compiled'].finditer(indications):
                        all_regex_matches.add(pattern_info['pattern'])
                        matched_diseases.update(diseases)  # All diseases are considered matched
                        drug_category = 'main_drug'
                        
                        context = extract_context_by_words(
                            indications, 
                            match.start(), 
                            match.end(), 
                            context_words
                        )
                        
                        drug_matches.append({
                            'pattern': pattern_info['pattern'],
                            'matched_text': match.group(),
                            'context': context,
                            'span': [match.start(), match.end()],
                            'type': 'main_drug'
                        })
                
                # Check secondary drug patterns only if no main patterns matched
                if drug_category == 'unrelated':
                    for pattern_info in treatment_patterns['secondary']:
                        for match in pattern_info['compiled'].finditer(indications):
                            all_regex_matches.add(pattern_info['pattern'])
                            matched_diseases.update(diseases)
                            drug_category = 'secondary_drug'
                            
                            context = extract_context_by_words(
                                indications, 
                                match.start(), 
                                match.end(), 
                                context_words
                            )
                            
                            drug_matches.append({
                                'pattern': pattern_info['pattern'],
                                'matched_text': match.group(),
                                'context': context,
                                'span': [match.start(), match.end()],
                                'type': 'secondary_drug'
                            })

                drug_results.append({
                    'drug_id': drug['id'],
                    'drug_name': drug['name'],
                    'category': drug_category,
                    'matches': drug_matches,
                    'indications': indications[:200] + '...' if len(indications) > 200 else indications
                })

            # Determine overall category (prioritize main_drug > secondary_drug > unrelated)
            overall_category = 'unrelated'
            for drug_result in drug_results:
                if drug_result['category'] == 'main_drug':
                    overall_category = 'main_drug'
                    break
                elif drug_result['category'] == 'secondary_drug' and overall_category == 'unrelated':
                    overall_category = 'secondary_drug'

            # Collect all text matches
            text_matches = []
            for drug_result in drug_results:
                for match in drug_result['matches']:
                    text_matches.append(match['context'])

            results[input_name] = {
                'match_status': len(all_regex_matches) > 0,
                'regex_matches': list(all_regex_matches),
                'category': overall_category,
                'text_matches': text_matches[:MAX_SNIPPETS],  # Limit text matches
                'matched_diseases': list(matched_diseases),
                'total_drugs_found': len(matches),
                'drug_details': drug_results
            }

        return {
            'diagnosis_text': diagnosis_text,
            'diseases': diseases,
            'disease_variants': disease_variants,
            'treatment_patterns': {
                'main_patterns': [p['pattern'] for p in treatment_patterns['main']],
                'secondary_patterns': [p['pattern'] for p in treatment_patterns['secondary']]
            },
            'results': results
        }

    except Exception as e:
        print(f"Lỗi khi phân loại thuốc: {e}")
        raise

# Test function
async def main():
    """Test the improved drug classification system"""
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    try:
        # Test case
        diagnosis_text = "Viêm họng cấp"
        drugs = ["Bilclamos", "Medrol", "Ileffexime", "cefprozil"]

        print(f"🔬 TESTING DRUG CLASSIFICATION SYSTEM")
        print(f"{'='*60}")
        print(f"Chẩn đoán: {diagnosis_text}")
        print(f"Thuốc cần kiểm tra: {drugs}")
        
        start_time = time.time()
        result = await check_drug_treatment_classification(
            diagnosis_text=diagnosis_text,
            drug_names=drugs,
            database_url=database_url,
            use_llm_filter=False,
            top_k=5,
            context_words=10
        )
        end_time = time.time()
        
        print(f"\n⏱️ Thời gian xử lý: {end_time - start_time:.2f}s")
        print(f"{'-'*60}")
        print("FULL RESSULT:", result)
        print(f"{'-'*60}")
        print(f"\n\n\n🏥 KẾT QUỂ PHÂN TÍCH:")
        print(f"Số bệnh tách được: {len(result['diseases'])}")
        print(f"Danh sách bệnh: {result['diseases']}")
        
        print(f"\n🧬 DISEASE VARIANTS:")
        for disease, variants in result['disease_variants'].items():
            print(f"  {disease}: {len(variants)} variants")
            if DEBUG:
                print(f"    → {variants[:3]}..." if len(variants) > 3 else f"    → {variants}")
        
        print(f"\n🔍 TREATMENT PATTERNS:")
        print(f"  Main patterns: {len(result['treatment_patterns']['main_patterns'])}")
        print(f"  Secondary patterns: {len(result['treatment_patterns']['secondary_patterns'])}")
        
        print(f"\n💊 KẾT QUẢ PHÂN LOẠI THUỐC:")
        for drug_name, drug_result in result['results'].items():
            print(f"\n📋 Thuốc: {drug_name}")
            print(f"  ✅ Match status: {drug_result['match_status']}")
            print(f"  🏷️  Category: {drug_result['category']}")
            print(f"  🔗 Matched diseases: {drug_result['matched_diseases']}")
            print(f"  📊 Total drugs found: {drug_result['total_drugs_found']}")
            print(f"  🧪 Regex matches: {len(drug_result['regex_matches'])}")
            
            if drug_result['regex_matches']:
                print(f"  📝 Sample regex: {drug_result['regex_matches'][0][:50]}...")
            
            if drug_result['text_matches']:
                print(f"  💬 Text matches:")
                for i, text_match in enumerate(drug_result['text_matches'][:2]):  # Show first 2
                    print(f"    {i+1}. {text_match}")
            
            if 'drug_details' in drug_result:
                print(f"  🔬 Drug details:")
                for j, drug_detail in enumerate(drug_result['drug_details'][:2]):  # Show first 2
                    print(f"    Drug {j+1}: {drug_detail['drug_name']} ({drug_detail['category']})")
                    print(f"      Matches: {len(drug_detail['matches'])}")

        print(f"\n{'='*60}")
        print("✅ Test completed successfully!")
        
        # # Test with LLM validation if API key is available
        # if os.getenv('OPENAI_API_KEY'):
        #     print(f"\n🤖 TESTING WITH LLM VALIDATION:")
        #     print(f"{'='*60}")
            
        #     start_time = time.time()
        #     result_with_llm = await check_drug_treatment_classification(
        #         diagnosis_text=diagnosis_text,
        #         drug_names=drugs,
        #         database_url=database_url,
        #         use_llm_filter=True,
        #         top_k=5,
        #         context_words=10
        #     )
        #     end_time = time.time()
            
        #     print(f"⏱️ Thời gian xử lý với LLM: {end_time - start_time:.2f}s")
            
        #     for drug_name, drug_result in result_with_llm['results'].items():
        #         print(f"\n📋 Thuốc: {drug_name}")
        #         print(f"  📊 Total drugs found: {drug_result['total_drugs_found']}")
                
        #         if 'drug_details' in drug_result:
        #             llm_validated = sum(1 for d in drug_result['drug_details'] 
        #                               if d.get('llm_validation', {}).get('is_suitable', True))
        #             print(f"  🤖 LLM validated: {llm_validated}/{len(drug_result['drug_details'])}")
        # else:
        #     print(f"\n⚠️  Không có OPENAI_API_KEY, bỏ qua test LLM validation")
        
    except Exception as e:
        print(f"❌ Lỗi trong test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())