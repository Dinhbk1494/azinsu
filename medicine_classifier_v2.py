from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union, Set, Tuple
from openai import AsyncAzureOpenAI
from fastapi import HTTPException
import os
from dotenv import load_dotenv
import uuid
import json
import re
import asyncpg
from dataclasses import dataclass
from difflib import SequenceMatcher

import unicodedata
from typing import cast

# Lazy import to avoid heavy dependencies at module import time
try:
    from simple_disease_checker_improved_v2 import (
        check_drug_list_by_multi_diseases_ilike as _db_check_drug_list_by_multi_diseases_ilike,
    )
    print("=========================== OK simple_disease_checker_improved")
except Exception:
    print("Exception==================================================")
    _db_check_drug_list_by_multi_diseases_ilike = None

load_dotenv()

# Configure Azure OpenAI
azure_api_key = os.getenv("AZURE_API_KEY")
openai_client = AsyncAzureOpenAI(
    api_version="2024-12-01-preview",
    azure_endpoint="https://admin-m9kv2jak-eastus2.cognitiveservices.azure.com/",
    api_key=azure_api_key,
    timeout=50.0,
    max_retries=3,
)

# Configure Database (Supabase Postgres)
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")



async def _log_event(dsn: Optional[str], request_id: str, phase: str, data: Dict):
    """Best-effort structured logging to Supabase (if DSN provided), else stdout.
    phase: one of ["input", "llm_output", "final"]
    """
    try:
        payload_json = json.loads(data, ensure_ascii=False)
    except Exception:
        # Fallback to string representation if not JSON-serializable
        payload_json = json.dumps({"repr": str(data)}, ensure_ascii=False)

    # Prefer DB logging when possible
    if dsn:
        try:
            conn = await asyncpg.connect(dsn=dsn)
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.medicine_logs (
                        id bigserial primary key,
                        request_id text,
                        phase text,
                        payload jsonb,
                        created_at timestamptz default now()
                    )
                    """
                )
                # Ensure optional analysis columns exist
                await conn.execute(
                    """
                    ALTER TABLE public.medicine_logs
                    ADD COLUMN IF NOT EXISTS changed boolean,
                    ADD COLUMN IF NOT EXISTS change_details jsonb
                    """
                )
                changed_value = None
                change_details_value = None
                try:
                    if phase == "final":
                        if isinstance(data, dict):
                            ch = data.get("changes")
                            changed_value = bool(ch) if ch is not None else None
                            change_details_value = json.dumps(ch, ensure_ascii=False) if ch is not None else None
                except Exception:
                    changed_value = None
                    change_details_value = None
                await conn.execute(
                    """
                    INSERT INTO public.medicine_logs(request_id, phase, payload, changed, change_details)
                    VALUES($1, $2, $3::jsonb, $4, $5::jsonb)
                    """,
                    request_id,
                    phase,
                    payload_json,
                    changed_value,
                    change_details_value,
                )
            finally:
                await conn.close()
            return
        except Exception as e:
            print(f"[log_event][db-fallback] request_id={request_id} phase={phase} err={str(e)}")

    # Stdout fallback
    print(f"[log_event] request_id={request_id} phase={phase} data={payload_json}")

@dataclass
class SearchResult:
    clinical_disease_id: int
    name: str
    score: float
    match_type: str
    matched_terms: List[str]

class AdvancedDiseaseSearch:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        
        # Medical synonyms and abbreviations
        self.synonyms = {
            # Hô hấp
            'viêm họng': ['viêm họng cấp tính', 'viêm họng mạn tính', 'đau họng', 'sưng họng'],
            'viêm phế quản': ['viêm phế quản cấp', 'viêm phế quản mạn', 'ho khan', 'ho có đờm'],
            'viêm mũi xoang': ['viêm xoang', 'viêm mũi dị ứng', 'sổ mũi', 'nghẹt mũi'],
            
            # Tiêu hóa
            'viêm dạ dày': ['viêm loét dạ dày', 'đau dạ dày', 'viêm dạ dày tá tràng'],
            'tiêu chảy': ['tiêu chảy cấp', 'rối loạn tiêu hóa', 'đau bụng'],
            
            # Tim mạch
            'tăng huyết áp': ['cao huyết áp', 'huyết áp cao', 'htn'],
            'suy tim': ['tim yếu', 'chf', 'congestive heart failure'],
            
            # Nội tiết
            'đái tháo đường': ['tiểu đường', 'đái tháo đường type 2', 'dm'],
            
            # Nhiễm trùng
            'sốt': ['sốt virus', 'sốt nhiễm khuẩn', 'sốt cao', 'sốt nhẹ'],
            'covid': ['covid-19', 'coronavirus', 'sars-cov-2'],
        }
        
        # Common abbreviations
        self.abbreviations = {
            'vhm': 'viêm họng mạn',
            'vpc': 'viêm phế quản cấp',
            'vdd': 'viêm dạ dày',
            'th': 'tăng huyết áp',
            'đtd': 'đái tháo đường',
        }
        
        # Medical stopwords (words to ignore)
        self.stopwords = {
            'bệnh', 'tình', 'trạng', 'của', 'và', 'hoặc', 'có', 'bị', 'mắc',
        'cấp', 'tính', 'mạn', 'tính', 'nhẹ', 'nặng', 'trung', 'bình'
        }

    def normalize_text(self, text: str) -> str:
        """Comprehensive text normalization"""
        if not text:
            return ""
        
        # Remove accents and special characters
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(c for c in text if not unicodedata.combining(c))
        
        # Convert to lowercase
        text = text.lower().strip()
        
        # Remove extra punctuation but keep hyphens and spaces
        text = re.sub(r'[^\w\s\-]', ' ', text)
        
        # Normalize multiple spaces and hyphens
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'-+', '-', text)
        
        return text

    def extract_keywords(self, text: str, remove_stopwords: bool = True) -> List[str]:
        """Extract meaningful keywords from text"""
        normalized = self.normalize_text(text)
        words = normalized.split()
        
        if remove_stopwords:
            words = [word for word in words if word not in self.stopwords and len(word) > 1]
        
        return words

    def expand_query(self, disease_name: str) -> Set[str]:
        """Expand query with synonyms, abbreviations, and variations"""
        queries = set()
        normalized = self.normalize_text(disease_name)
        queries.add(normalized)
        
        # Add original query variations
        queries.add(disease_name.lower().strip())
        
        # Expand abbreviations
        if normalized in self.abbreviations:
            queries.add(self.abbreviations[normalized])
        
        # Expand synonyms
        for term, synonyms in self.synonyms.items():
            if term in normalized or any(syn in normalized for syn in synonyms):
                queries.add(term)
                queries.update(synonyms)
        
        # Add partial matches for compound terms
        words = self.extract_keywords(normalized)
        if len(words) > 1:
            # Add individual words
            queries.update(words)
            # Add bigrams
            for i in range(len(words) - 1):
                queries.add(f"{words[i]} {words[i+1]}")
        
        return queries

    async def search_exact_match(self, queries: Set[str]) -> List[SearchResult]:
        """Exact match with highest priority"""
        results = []
        
        async with self.pool.acquire() as conn:
            for query in queries:
                rows = await conn.fetch(
                    """
                    SELECT clinical_disease_id, name
                    FROM public.clinical_diseases
                    WHERE LOWER(TRIM(name)) = $1
                    """,
                    query
                )
                
                for row in rows:
                    results.append(SearchResult(
                        clinical_disease_id=row['clinical_disease_id'],
                        name=row['name'],
                        score=10.0,  # Highest score for exact match
                        match_type='exact',
                        matched_terms=[query]
                    ))
        
        return results

    async def search_prefix_match(self, queries: Set[str]) -> List[SearchResult]:
        """Prefix matching for autocomplete-like behavior"""
        results = []
        
        async with self.pool.acquire() as conn:
            for query in queries:
                if len(query) >= 3:  # Only for queries with 3+ characters
                    rows = await conn.fetch(
                        """
                        SELECT clinical_disease_id, name,
                               CASE 
                                   WHEN LOWER(name) LIKE $1 THEN 8.0
                                   WHEN LOWER(name) LIKE $2 THEN 6.0
                                   ELSE 4.0
                               END as score
                        FROM public.clinical_diseases
                        WHERE LOWER(name) LIKE $1 OR LOWER(name) LIKE $2 OR LOWER(name) LIKE $3
                        """,
                        f"{query}%",      # Starts with query
                        f"% {query}%",    # Word starts with query
                        f"%{query}%"      # Contains query
                    )
                    
                    for row in rows:
                        results.append(SearchResult(
                            clinical_disease_id=row['clinical_disease_id'],
                            name=row['name'],
                            score=float(row['score']),
                            match_type='prefix',
                            matched_terms=[query]
                        ))
        
        return results

    async def search_fuzzy_postgresql(self, queries: Set[str], min_similarity: float = 0.5) -> List[SearchResult]:
        """Fuzzy matching using PostgreSQL pg_trgm extension"""
        results = []
        
        async with self.pool.acquire() as conn:
            try:
                # Try to enable pg_trgm extension
                await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                
                for query in queries:
                    if len(query) >= 4:  # Only for longer queries
                        rows = await conn.fetch(
                            """
                            SELECT clinical_disease_id, name,
                                   SIMILARITY(LOWER(name), $1) as similarity,
                                   WORD_SIMILARITY($1, LOWER(name)) as word_sim
                            FROM public.clinical_diseases
                            WHERE SIMILARITY(LOWER(name), $1) > $2
                               OR WORD_SIMILARITY($1, LOWER(name)) > $2
                            ORDER BY GREATEST(SIMILARITY(LOWER(name), $1), WORD_SIMILARITY($1, LOWER(name))) DESC
                            """,
                            query, min_similarity
                        )
                        
                        for row in rows:
                            similarity = max(float(row['similarity']), float(row['word_sim']))
                            results.append(SearchResult(
                                clinical_disease_id=row['clinical_disease_id'],
                                name=row['name'],
                                score=similarity * 7.0,  # Scale up similarity score
                                match_type='fuzzy_pg',
                                matched_terms=[query]
                            ))
                            
            except Exception:
                # Fallback to Python fuzzy matching
                pass
        
        return results

    async def search_fuzzy_python(self, queries: Set[str], min_similarity: float = 0.1) -> List[SearchResult]:
        """Fallback fuzzy matching using Python difflib"""
        results = []
        
        async with self.pool.acquire() as conn:
            # Get all disease names for comparison
            all_diseases = await conn.fetch("SELECT clinical_disease_id, name FROM public.clinical_diseases")
            
            for row in all_diseases:
                disease_name = self.normalize_text(row['name'])
                max_similarity = 0.0
                best_match_term = ""
                
                for query in queries:
                    if len(query) >= 3:
                        similarity = SequenceMatcher(None, query, disease_name).ratio()
                        
                        # Also check word-level similarity for multi-word queries
                        query_words = query.split()
                        disease_words = disease_name.split()
                        
                        if len(query_words) > 1 and len(disease_words) > 1:
                            word_similarities = []
                            for q_word in query_words:
                                best_word_sim = max(
                                    (SequenceMatcher(None, q_word, d_word).ratio() 
                                     for d_word in disease_words), 
                                    default=0
                                )
                                word_similarities.append(best_word_sim)
                            
                            # Average word similarity
                            avg_word_sim = sum(word_similarities) / len(word_similarities)
                            similarity = max(similarity, avg_word_sim)
                        
                        if similarity > max_similarity:
                            max_similarity = similarity
                            best_match_term = query
                
                if max_similarity >= min_similarity:
                    results.append(SearchResult(
                        clinical_disease_id=row['clinical_disease_id'],
                        name=row['name'],
                        score=max_similarity * 5.0,  # Scale similarity score
                        match_type='fuzzy_python',
                        matched_terms=[best_match_term]
                    ))
        
        return results

    async def search_full_text(self, queries: Set[str]) -> List[SearchResult]:
        """Full-text search using PostgreSQL tsvector"""
        results = []
        
        async with self.pool.acquire() as conn:
            for query in queries:
                try:
                    # Create search query with AND and OR operators
                    query_words = self.extract_keywords(query, remove_stopwords=False)
                    if not query_words:
                        continue
                    
                    # Try different query strategies
                    search_queries = [
                        ' & '.join(query_words),  # All words must match
                        ' | '.join(query_words),  # Any word can match
                        query  # Phrase search
                    ]
                    
                    for search_query in search_queries:
                        rows = await conn.fetch(
                            """
                            SELECT clinical_disease_id, name,
                                   ts_rank_cd(to_tsvector('simple', name), query) as rank
                            FROM public.clinical_diseases,
                                 plainto_tsquery('simple', $1) query
                            WHERE to_tsvector('simple', name) @@ query
                            AND ts_rank_cd(to_tsvector('simple', name), query) > 0
                            ORDER BY rank DESC
                            """,
                            search_query
                        )
                        
                        for row in rows:
                            rank = float(row['rank'])
                            if rank > 0:
                                results.append(SearchResult(
                                    clinical_disease_id=row['clinical_disease_id'],
                                    name=row['name'],
                                    score=rank * 6.0,  # Scale rank score
                                    match_type='fulltext',
                                    matched_terms=query_words
                                ))
                        
                        if rows:  # If we found results with this strategy, don't try others
                            break
                            
                except Exception:
                    # Full-text search failed, continue with other methods
                    pass
        
        return results

    async def search_keyword_match(self, queries: Set[str]) -> List[SearchResult]:
        """Multi-keyword matching with scoring"""
        results = []
        
        async with self.pool.acquire() as conn:
            for query in queries:
                keywords = self.extract_keywords(query)
                if not keywords:
                    continue
                
                # Create ILIKE patterns for each keyword
                like_conditions = []
                params = []
                for i, keyword in enumerate(keywords, 1):
                    like_conditions.append(f"LOWER(name) ILIKE ${i}")
                    params.append(f"%{keyword}%")
                
                if like_conditions:
                    sql = f"""
                    SELECT clinical_disease_id, name,
                           ({' + '.join([f"CASE WHEN LOWER(name) ILIKE ${i} THEN 1 ELSE 0 END" 
                                       for i in range(1, len(keywords) + 1)])}) as match_count
                    FROM public.clinical_diseases
                    WHERE {' OR '.join(like_conditions)}
                    ORDER BY match_count DESC, length(name)
                    """
                    
                    rows = await conn.fetch(sql, *params)
                    
                    for row in rows:
                        match_count = row['match_count']
                        # Score based on how many keywords matched
                        score = (match_count / len(keywords)) * 3.0
                        
                        results.append(SearchResult(
                            clinical_disease_id=row['clinical_disease_id'],
                            name=row['name'],
                            score=score,
                            match_type='keyword',
                            matched_terms=keywords[:match_count]
                        ))
        
        return results

    def deduplicate_and_rank(self, results: List[SearchResult], limit: int = 3) -> List[SearchResult]:
        """Advanced deduplication and ranking"""
        # Group by clinical_disease_id
        disease_groups = {}
        
        for result in results:
            disease_id = result.clinical_disease_id
            if disease_id not in disease_groups:
                disease_groups[disease_id] = []
            disease_groups[disease_id].append(result)
        
        # For each disease, combine scores and select best match type
        final_results = []
        
        for disease_id, group in disease_groups.items():
            # Sort by score descending
            group.sort(key=lambda x: x.score, reverse=True)
            best_result = group[0]
            
            # Combine scores from different match types (with diminishing returns)
            combined_score = best_result.score
            bonus_score = 0
            
            match_types_seen = {best_result.match_type}
            for result in group[1:]:
                if result.match_type not in match_types_seen:
                    bonus_score += result.score * 0.3  # 30% bonus for additional match types
                    match_types_seen.add(result.match_type)
            
            # Combine matched terms
            all_matched_terms = set()
            for result in group:
                all_matched_terms.update(result.matched_terms)
            
            final_result = SearchResult(
                clinical_disease_id=disease_id,
                name=best_result.name,
                score=combined_score + bonus_score,
                match_type=best_result.match_type,
                matched_terms=list(all_matched_terms)
            )
            
            final_results.append(final_result)
        
        # Sort by final score and return top results
        final_results.sort(key=lambda x: x.score, reverse=True)
        return final_results[:limit]

    async def search_diseases(self, disease_name: str, limit: int = 3) -> List[SearchResult]:
        """Main search function combining all strategies"""
        if not disease_name or not disease_name.strip():
            return []
        
        # Expand query
        print("disease_name: ", disease_name)
        expanded_queries = [disease_name] #self.expand_query(disease_name)
        print("expanded_queries: ", expanded_queries)
        
        all_results = []
        
        # Strategy 1: Exact Match (highest priority)
        exact_results = await self.search_exact_match(expanded_queries)
        # print("exact_results: ", exact_results)
        all_results.extend(exact_results)
        
        # Strategy 2: Prefix Match
        prefix_results = await self.search_prefix_match(expanded_queries)
        # print("prefix_results: ", prefix_results)
        all_results.extend(prefix_results)
        
        # Strategy 3: PostgreSQL Fuzzy Match
        fuzzy_pg_results = await self.search_fuzzy_postgresql(expanded_queries)
        # print("fuzzy_pg_results: ", fuzzy_pg_results)
        all_results.extend(fuzzy_pg_results)
        
        # Strategy 4: Full-text Search
        fulltext_results = await self.search_full_text(expanded_queries)
        # print("fulltext_results: ", fulltext_results)
        all_results.extend(fulltext_results)
        
        # Strategy 5: Keyword Match
        keyword_results = await self.search_keyword_match(expanded_queries)
        # print("keyword_results: ", keyword_results)
        all_results.extend(keyword_results)
        
        # Strategy 6: Python Fuzzy Match (fallback, only if few results)
        if len(all_results) < limit * 2:
            python_fuzzy_results = await self.search_fuzzy_python(expanded_queries)
            # print("python_fuzzy_results: ", python_fuzzy_results)
            all_results.extend(python_fuzzy_results)
        
        # Deduplicate and rank
        return self.deduplicate_and_rank(all_results, limit)

# Main function - drop-in replacement for the original
async def _fetch_top3_clinical_diseases(pool: asyncpg.Pool, disease_name: str) -> List[Dict]:
    """
    Enhanced version of the original function with advanced search capabilities.
    Returns the same format for backward compatibility.
    """
    search_engine = AdvancedDiseaseSearch(pool)
    results = await search_engine.search_diseases(disease_name, limit=3)
    
    # Convert to original format
    return [
        {
            "clinical_disease_id": result.clinical_disease_id,
            "name": result.name
        }
        for result in results
    ]
    
    
    
    
async def _split_diseases_with_llm(symptom: Optional[str]) -> List[str]:
    """
    Use LLM to split the input symptom/diagnosis text into independent diseases (0 if none).
    Returns a list of disease strings (max 4 to avoid explosion).
    """
    if not symptom:
        return []

    system = (
        "Bạn là trợ lý y khoa. Hãy trích ra danh sách các bệnh/chẩn đoán độc lập từ đoạn mô tả. "
        "Chỉ trả về JSON dạng {\"diseases\":[\"...\"]} với 1-4 bệnh, loại bỏ trùng lặp, gọn, không kèm triệu chứng rời rạc."
    )
    user = json.dumps({"symptom": symptom}, ensure_ascii=False)

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            top_p=0,
            response_format={"type": "json_object"}
        )
        text = response.choices[0].message.content
        try:
            obj = json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            obj = json.loads(m.group(0)) if m else {"diseases": []}
        diseases = obj.get("diseases", [])
        if not isinstance(diseases, list):
            return []
        # normalize
        cleaned = []
        seen = set()
        for d in diseases[:4]:
            if not isinstance(d, str):
                continue
            s = d.strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                cleaned.append(s)
        return cleaned
    except Exception:
        return []

async def _validate_diseases_with_llm(
    symptom: str, 
    top3_diseases: List[Dict], 
    pool: asyncpg.Pool
) -> List[Dict]:
    """
    Validate top 3 diseases with LLM against original symptom.
    If diseases are reasonable, keep them. If not, find similar diseases or return empty.
    
    Args:
        symptom: Original symptom text
        top3_diseases: List of top 3 diseases from database
        pool: Database connection pool
    
    Returns:
        List of validated diseases (can be empty if none are reasonable)
    """
    if not top3_diseases:
        return []
    
    # Prepare disease names for LLM evaluation
    disease_names = [d["name"] for d in top3_diseases]
    
    system = (
        "Bạn là bác sĩ chuyên khoa. Hãy đánh giá xem các bệnh được đề xuất có phù hợp với triệu chứng gốc không.\n"
        "Trả về JSON dạng: {\"valid_diseases\": [\"tên bệnh hợp lý\"], \"reason\": \"lý do\"}\n"
        "Chỉ giữ lại những bệnh thực sự liên quan đến triệu chứng. Nếu không có bệnh nào hợp lý, trả về mảng rỗng."
    )
    
    user = json.dumps({
        "symptom": symptom,
        "proposed_diseases": disease_names
    }, ensure_ascii=False)
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            top_p=0,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content
        try:
            obj = json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            obj = json.loads(m.group(0)) if m else {"valid_diseases": []}
        
        valid_disease_names = obj.get("valid_diseases", [])
        reason = obj.get("reason", "")
        
        print(f"LLM validation result: {valid_disease_names}, reason: {reason}")
        
        if not valid_disease_names:
            print("No diseases validated by LLM, returning empty list")
            return []
        
        # Filter top3_diseases to only include validated ones
        validated_diseases = [
            d for d in top3_diseases 
            if d["name"] in valid_disease_names
        ]
        
        # If we have validated diseases, return them
        if validated_diseases:
            print(f"Returning {len(validated_diseases)} validated diseases")
            return validated_diseases
        
        # If no diseases were validated, try to find similar diseases
        print("No diseases validated, trying to find similar diseases...")
        return await _find_similar_diseases(symptom, pool)
        
    except Exception as e:
        print(f"Error in LLM validation: {str(e)}")
        # Fallback: try to find similar diseases
        return await _find_similar_diseases(symptom, pool)

async def _find_similar_diseases(symptom: str, pool: asyncpg.Pool) -> List[Dict]:
    """
    Find similar diseases when LLM validation fails.
    Uses broader search to find potentially relevant diseases.
    """
    try:
        # Use a broader search pattern
        search_terms = symptom.split()
        broader_patterns = []
        
        # Create multiple search patterns
        for i in range(len(search_terms)):
            for j in range(i + 1, min(i + 4, len(search_terms) + 1)):
                pattern = " ".join(search_terms[i:j])
                if len(pattern) > 2:  # Only meaningful patterns
                    broader_patterns.append(pattern)
        
        # Add the original symptom
        broader_patterns.append(symptom)
        
        all_matches = []
        seen_ids = set()
        
        for pattern in broader_patterns[:5]:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT clinical_disease_id, name
                    FROM public.clinical_diseases
                    WHERE name ILIKE $1
                    ORDER BY length(name)
                    LIMIT 2
                    """,
                    f"%{pattern}%"
                )
                
                for row in rows:
                    if row["clinical_disease_id"] not in seen_ids:
                        seen_ids.add(row["clinical_disease_id"])
                        all_matches.append({
                            "clinical_disease_id": row["clinical_disease_id"],
                            "name": row["name"]
                        })
        
        # Return top 3 most relevant (shorter names are usually more specific)
        return sorted(all_matches, key=lambda x: len(x["name"]))[:3]
        
    except Exception as e:
        print(f"Error finding similar diseases: {str(e)}")
        return []

# async def _fetch_top3_clinical_diseases(pool: asyncpg.Pool, disease_name: str) -> List[Dict]:
#     """
#     Find top 3 similar clinical diseases by name using ILIKE fallback.
#     """
#     like_pattern = f"%{disease_name}%"
#     async with pool.acquire() as conn:
#         rows = await conn.fetch(
#             """
#             SELECT clinical_disease_id, name
#             FROM public.clinical_diseases
#             WHERE name ILIKE $1 OR name ILIKE $2
#             ORDER BY CASE WHEN name ILIKE $3 THEN 0 ELSE 1 END, length(name)
#             LIMIT 3
#             """,
#             like_pattern,
#             like_pattern.replace(" ", "%"),
#             like_pattern
#         )
#     return [{"clinical_disease_id": r["clinical_disease_id"], "name": r["name"]} for r in rows]

async def _fetch_protocol_rules_for_diseases(pool: asyncpg.Pool, disease_ids: List[int]) -> List[Dict]:
    if not disease_ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rule_id, protocol_id, clinical_disease_id, rule_group, 
                   condition_to_apply, rule_description
            FROM public.protocol_rules
            WHERE protocol_id = 9001 AND clinical_disease_id = ANY($1::int[])
            """,
            disease_ids
        )
    return [dict(r) for r in rows]

async def _adjudicate_roles_with_llm(
    items_with_ids: List[Dict[str, str]],
    initial_results: List[Dict],
    diseases: List[str],
    disease_matches: Dict[str, List[Dict]],
    rules: List[Dict]
) -> List[Dict]:
    """
    Ask LLM to adjust only the role field using DB rules. Prioritize DB rule_group when there is a clear match
    between a medicine name and any rule_description for the matched diseases.
    """
    # Build compact context
    initial = [
        {
            "id": r["id"],
            "name": r.get("name"),
            "category": r.get("category"),
            "validity": r.get("validity"),
            "role": r.get("role"),
        }
        for r in initial_results
    ]
    disease_to_rules = {}
    for d, matches in disease_matches.items():
        ids = [m["clinical_disease_id"] for m in matches]
        disease_to_rules[d] = [r for r in rules if r.get("clinical_disease_id") in ids]

    system = (
        "Bạn là hệ thống đối chiếu phác đồ. Tôi sẽ lấy thông tin thuốc chính/hỗ trợ từ phác đồ chuẩn 'disease_to_rules', hãy ưu tiên thông tin thưo phác đồ. Nhiệm vụ: CHỈ cập nhật trường 'role' (main drug/secondary drug) cho các mục category='drug'. "
        "'initial' là thông tin phân loại hiện tại của một số thẩm định viên và AI (có thể chưa chính xác)" 
        "ƯU TIÊN TUYỆT ĐỐI quy tắc từ CSDL nếu thông tin bệnh và thuốc cần phân loại được đề cập trong 'disease_to_rules', nếu tên thuốc khớp hoặc rất gần với 'drugs name' của bệnh tương ứng thì lấy 'standard drug classification' làm kết luận về thuốc chính/phụ. "
        "disease_to_rules.('disease name') có thể tên không trùng khớp với bệnh gốc, nhưng nếu bạn thấy có mỗi liên hệ thì có thế tham chiếu, không nhất thiết phảo trùng khớp hoàn toàn"
        "Đặc biệt lưu lý: phác đồ chỉ có một số thuốc, không thể bao phủ tất cả, do đó tất cả các thuốc nếu không được nhắc đến trong phác đồ thì hãy giữ nguyên kết quả ban đầu mà không thay đổi"
        "Nếu không khớp rõ ràng, giữ nguyên role hiện có. Trả về JSON: {\"results\":[{id, role}]}."
    )
    user_payload = {
        "initial": initial,
        "diseases": diseases,
        "disease_to_rules": {
            d: [
                {
                    "disease name": d,
                    "standard drug classification": r.get("rule_group"),
                    "drugs name": r.get("rule_description"),
                }
                for r in rs
            ]
            for d, rs in disease_to_rules.items()
        },
    }
    try:
        # print('payload: ', str(user_payload))
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0,
            top_p=0,
            response_format={"type": "json_object"}
        )
        text = response.choices[0].message.content
        try:
            obj = json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            obj = json.loads(m.group(0)) if m else {"results": []}
        updates = obj.get("results", [])
        update_map = {u.get("id"): u.get("role") for u in updates if u.get("id")}
        # Apply updates only to role
        merged = []
        for r in initial_results:
            rid = r["id"]
            new_role = update_map.get(rid, r.get("role"))
            merged.append({**r, "role": new_role})
        return merged
    except Exception:
        return initial_results

class MedicineItem(BaseModel):
    id: str = Field(..., description="Unique identifier for the medicine")
    name: str = Field(..., description="Name of the medicine")

class MedicineRequest(BaseModel):
    items: Union[List[str], List[MedicineItem]] = Field(
        ..., 
        description="Danh sách tên thuốc được kê đơn. Có thể là list of strings hoặc list of objects với id và name",
        examples=[
            # Example 2: List of objects with id and name
            [
                {"id": "a1f2c3", "name": "Paracetamol 500mg"},
                {"id": "b4d5e6", "name": "Amoxicillin 500mg"},
                {"id": "c7g8h9", "name": "Cetirizine 10mg"},
                {"id": "d0i1j2", "name": "Vitamin C 1000mg"}
            ],
            # Example 1: List of strings
            [
                "Paracetamol 500mg",
                "Amoxicillin 500mg",
                "Cetirizine 10mg",
                "Vitamin C 1000mg"
            ]
        ]
    )
    symptom: Optional[str] = Field(
        None, 
        description="Kết luận/chẩn đoán của bác sĩ",
        example="Viêm họng cấp tính kèm sốt nhẹ. Có dấu hiệu dị ứng theo mùa."
    )
    request_id: Optional[str] = Field(
        None,
        description="Request ID để truy vết; nếu không truyền sẽ tự sinh"
    )

class MedicineResult(BaseModel):
    id: str
    name: str
    category: str
    validity: str
    role: str
    explanation: str

class MedicineResponse(BaseModel):
    results: List[MedicineResult]
    request_id: str
    changes: Optional[List[Dict]] = None
    changed: Optional[bool] = None
    change_details: Optional[List[Dict]] = None

    class Config:
        from_attributes = True


def _get_bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


async def classify_with_gpt4(
    items: Union[List[str], List[MedicineItem]],
    symptom: str = None,
    request_id: Optional[str] = None,
    enable_llm_validation: bool = False,
    # Feature flags (request-level; fallback to ENV)
    enable_db_disease_checker: Optional[bool] = False,
    enable_protocol_rules: Optional[bool] = True,
    force_protocol_rules: Optional[bool] = None,
    conservative_mode: Optional[bool] = None,
) -> Dict[str, list]:
    """
    Classify items using Azure OpenAI GPT-4 API with enhanced examples
    
    Args:
        items: List of medicine items or strings to classify
        symptom: Symptom/diagnosis text for context
        request_id: Optional request ID for logging
        enable_llm_validation: If True, use LLM to validate top 3 diseases against original symptom.
                              If False, use raw top 3 diseases without validation.
    
    Returns:
        Dictionary with classifications and explanations
    """
    # Correlate logs via request_id
    request_id = request_id or str(uuid.uuid4())

    # Handle different input formats and prepare items with IDs
    dsn_for_logging: Optional[str] = SUPABASE_DB_URL
    # Nếu không có từ env, thử tự build từ env khác (giữ nguyên hành vi cũ)
    if not dsn_for_logging:
        host = "db.jhxutciiidfpnhbnmyjc.supabase.co"
        user = "postgres"
        password = "Motconvit131294"
        dbname = "postgres"
        dsn_for_logging = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    if isinstance(items[0], str):
        # If input is list of strings, generate UUIDs
        items_with_ids = [{"id": str(uuid.uuid4())[:6], "name": item} for item in items]
    else:
        # If input is list of objects, use provided IDs
        items_with_ids = [{"id": item.id, "name": item.name} for item in items]

    # Resolve feature flags (request param > ENV > defaults)
    _enable_db_checker = enable_db_disease_checker if enable_db_disease_checker is not None else _get_bool_env("MEDCLS_ENABLE_DB_CHECKER", True)
    _enable_rules = enable_protocol_rules if enable_protocol_rules is not None else _get_bool_env("MEDCLS_ENABLE_RULES", True)
    _force_rules = force_protocol_rules if force_protocol_rules is not None else _get_bool_env("MEDCLS_FORCE_RULES", False)
    _conservative = conservative_mode if conservative_mode is not None else _get_bool_env("MEDCLS_CONSERVATIVE", False)
    
    system = """
    Bạn là chuyên gia dược phẩm với nhiệm vụ phân loại các mục được cung cấp và giải thích chi tiết về mỗi phân loại.
    
    Phân loại theo các tiêu chí sau. Bạn LUÔN LUÔN thực hiện các nhiệm vụ cụ thể rõ ràng sau đây, ƯU TIÊN các định nghĩa và ví dụ trong prompt này hơn bất kỳ kiến thức nào khác:

    1. category:
        - "drug": là thuốc, cụ thể như sau:
            + Thuốc điều trị bệnh cụ thể (kháng sinh, giảm đau, v.v.)
            + Vitamin/khoáng chất khi:
                * Điều trị bệnh lý cụ thể theo chẩn đoán
                * Có liều lượng điều trị cụ thể (VD: Vitamin C 1000mg)
                * Ngăn ngừa tác dụng phụ của thuốc khác
            + Nếu tên thuốc là một vị thuốc Đông y cụ thể hoặc một bài thuốc cổ truyền (ví dụ: Ngưu tất, Độc hoạt tang ký sinh, Boganic) VÀ có "symptom" thì được coi là thuốc
        - "nodrug": Không phải thuốc
            
    2. validity: "valid" hoặc "invalid" dựa trên chẩn đoán. Hiện tại tất cả đều hợp lệ, nên mặc định xem nó là 'valid', không được phép chọn 'invalid'
        - "valid": Phù hợp với chẩn đoán hoặc thuốc hỗ trợ, giảm tác dụng phụ thuốc chính, chỉ cần có liên quan đến bệnh, triệu chứng chính/phụ/liên quan thì đều coi là hợp lệ.
        - "invalid": Không phù hợp với chẩn đoán/bất cứ triệu chứng nào hoặc không phải là thuốc hỗ trợ, hay không giảm tác dụng phụ thuốc chính
        - note1: Nếu có chẩn đoán, thì chỉ cần có liên quan đến bệnh, triệu chứng chính/phụ/liên quan thì đều coi là hợp lệ. Rất cẩn trọng đánh giá invalid
        - note2: Mặc định "valid" nếu không có chẩn đoán
        
    3. role: Phân loại vai trò của item
        Nếu category là "drug":
            - "main drug" được định nghĩa như sau:
                * Thuốc ĐIỀU TRỊ bệnh (nguyên nhân/cơ chế sinh bệnh) hay triệu chứng (triệu chứng chính (ví dụ: viêm họng có triệu chứng chính là đau họng) và tất cả triệu chứng liên quan đến bệnh (ví dụ: sốt cao -> dẫn đến mất nước là triệu chứng liên quan)) của ít nhất 1 trong các bệnh nằm trong  'symptom' (một chẩn đoán có thể có nhiều bệnh):
                    - Kháng sinh, kháng virus, kháng nấm, kháng lao, trị sốt rét,...
                    - Thuốc đặc trị bệnh mạn tính: Dùng cho các bệnh lý mạn tính được chẩn đoán.
                * Thuốc HỖ TRỢ điều trị bệnh/triệu chứng của ít nhất 1 trong các bệnh nằm trong 'symptom':
                    - Thuốc giảm đau, hạ sốt, kháng viêm (NSAIDs, Corticosteroids, Paracetamol). Ví dụ: Celebrex (Celecoxib), Medrol (Methylprednisolon) cho "Thoái hóa cột sống", "Chấn thương lưng". Paracetamol cho "Sốt nhiễm khuẩn".
                    - Thuốc điều trị triệu chứng hô hấp, ví dụ: Ambroxol (long đờm), Terbutaline (giãn phế quản), Desloratadin (chống dị ứng, sổ mũi) cho các bệnh "Viêm phế quản", "Viêm mũi họng".
                    - Thuốc điều trị triệu chứng tiêu hóa. Ví dụ: Hidrasec (chống tiêu chảy), Buscopan (chống co thắt), Esomeprazol (giảm tiết acid dạ dày) cho "Tiêu chảy cấp", "Viêm dạ dày", "Trào ngược dạ dày-thực quản"; hay Men vi sinh (Probiotics) cho các bệnh mà có thể có triệu chứng rối loạn tiêu hóa như "viêm nhiễm đường tiêu hóa", "ngộ độc thực phẩm".
                    - Thuốc điều trị tại chỗ. Ví dụ: Ileffexime (nhỏ tai) cho "Viêm ống tai ngoài". Fucidin H (kem bôi) cho "Viêm da tiếp xúc dị ứng". Voltaren Emulgel (gel bôi) cho "Nang hoạt dịch".
                * Thuốc cải thiện trực tiếp quá trình hồi phục quan trọng của bệnh (ví dụ: thuốc bổ sung canxi cho gãy xương, thuốc bổ sung lợi khuẩn cho rối loạn tiêu hóa)
                * Nếu thuốc là vitamin kết hợp với loại khác (ví dụ: Nhôm hydroxyd + Magnesium hydroxide) thì sẽ coi là "main drug"
                * Thuốc bổ sung để điều trị một bệnh thiếu hụt đã được chẩn đoán. Ví dụ Nếu vitamin hay thành phần chính là vitamin, nhưng chẩn đoán bệnh có liên quan thiếu vitamin hay điện giải thì lúc này đây được coi là "main drug"
                * Cung cấp thành phần thiết yếu và trực tiếp cho quá trình sửa chữa cấu trúc hoặc phục hồi chức năng bị tổn thương bởi bệnh. Ví dụ thuốc Canxi cho bệnh gãy xương

            - "secondary drug" được định nghĩa như sau:
                * Thuốc làm giảm tác dụng phụ của thuốc chính
                * Thuốc bảo vệ dạ dày (nhóm PPI): Khi dùng kèm với các thuốc kháng viêm NSAIDs hoặc Corticosteroids.
                * Vitamin không ghi rõ liều lượng, hay không liên quan đến chẩn đoán
                * Men vi sinh (Probiotics): Khi dùng kèm với kháng sinh để ngừa tiêu chảy. Ví dụ: Enterogermina (Bacillus clausii) là "Thuốc hỗ trợ" khi đi kèm kháng sinh Augmentin trong đơn "Sốt nhiễm khuẩn - Viêm mũi họng cấp".
                * Thuốc dự phòng
                * Thuốc tăng cường miễn dịch. Các thuốc này không trực tiếp tiêu diệt mầm bệnh hay giảm triệu chứng mà có vai trò điều hòa, hỗ trợ hệ miễn dịch. Ví dụ: GreenPam (Thymomodulin) cho "Sốt phát ban". Althax (Thymomodulin) cho "Viêm mũi xoang cấp".
                * Thuốc không cải thiện trực tiếp quá trình hồi phục quan trọng của bệnh (ví dụ: đối với viêm gan B, thì quá trình hồi phục quan trọng là tiêu diệt hoặc kiểm soát virus HBV, do đó thuốc Silymarin chỉ bổ gan, bảo vệ gan không phải là thuốc chính mà là thuốc hỗ trợ)
        
        Nếu category là "nodrug":
            - "supplement": Thực phẩm chức năng, vitamin bổ sung và không phải là thuốc
            - "medical supplies": Vật tư y tế và không phải là thuốc
            - "medical equipment": Thiết bị y tế và không phải là thuốc
            - "cosmeceuticals": Mỹ phẩm có tác dụng điều trị và không phải là thuốc
            - "other": Không xác định được và không phải là thuốc
        Nếu validity là 'invalid', thì không cần phân loại role, trả về string rỗng ''
        
    4. explanation:
        Giải thích ngắn gọn lý do phân loại, tập trung vào:
            - Tác dụng của thuốc/sản phẩm
            - Thành phần của thuốc
            - Mối liên quan với chẩn đoán
            - Lý do phân loại vai trò

    Lưu ý đặc biệt:
        - Tuyệt đối phân loại theo các định nghĩa của tôi
        - Các thuốc có xu hướng là 'main drug', nên nếu không có chứng cứ thật sự rõ ràng là 'secondary drug' thì mặc định là 'main drug'
        - Nhiều khả năng 1 đơn thuốc chỉ chứa thuốc chính 'main drug' mà không có thuốc hỗ trợ 'secondary drug'.
    
    
    Trả về kết quả dạng JSON với format:
    {
      "results": [
        {
          "id": "uuid của item",
          "category": "drug/nodrug",
          "validity": "valid/invalid",
          "role": "main drug/secondary drug" cho drug hoặc "supplement/medical_supplies/medical_equipment/cosmeceuticals/other" cho nodrug,
          "explanation": "Giải thích lý do phân loại"
        },
        ...
      ]
    }

    Ví dụ input:
    {
      "items": [
        { "id": "a1b2c3", "name": "Paracetamol 500mg" },
        { "id": "g7h8i9", "name": "Khẩu trang y tế" }
      ],
      "symptom": "Sốt virus, đau họng"
    }

    Ví dụ output:
    {
      "results": [
        {
          "id": "a1b2c3",
          "category": "drug",
          "validity": "valid",
          "role": "main drug",
          "explanation": "Paracetamol là thuốc hạ sốt, giảm đau phù hợp với triệu chứng sốt và đau họng."
        },
        {
          "id": "g7h8i9",
          "category": "nodrug",
          "validity": "valid",
          "role": "medical supplies",
          "explanation": "Khẩu trang là vật tư y tế dùng để phòng ngừa lây nhiễm."
        }
      ]
    }
    
    Hãy chỉ cho output dạng JSON mà không có bất kì chú thích gì thêm.
    """

    # Format input data
    input_data = {
        "items": items_with_ids,
        "symptom": symptom if symptom else "Chưa có thông tin chi tiết về kết quả khám bệnh",
        "flags": {
            "enable_db_disease_checker": _enable_db_checker,
            "enable_protocol_rules": _enable_rules,
            "force_protocol_rules": _force_rules,
            "conservative_mode": _conservative,
        },
    }
    await _log_event(dsn_for_logging, request_id, "input", input_data)
    
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)}
        ]
        
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0,
                seed=42,
                # top_p=0,
                presence_penalty=0,
                frequency_penalty=0,
                response_format={"type": "json_object"}
            )
            # Log raw LLM output text
            response_text_for_log = response.choices[0].message.content if response and response.choices else ""
            await _log_event(dsn_for_logging, request_id, "llm_output", {"raw": json.loads(response_text_for_log)})
       
        except Exception as e:
            # Normalize wrapped network errors to 503 as well
            print("Error in classify_with_gpt4:", str(e))
        
        # Get response and parse JSON
        response_text = response.choices[0].message.content
        # Convert response to Python dict (with robust fallback)
        try:
            response_dict = json.loads(response_text)
            print("response_dict: ", response_dict)
        except Exception:
            # Fallback: try to extract the first JSON object from the text
            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if not json_match:
                raise
            response_dict = json.loads(json_match.group(0))
        # Create final response with both id and name
        initial_results: List[Dict] = []
        name_map = {item["id"]: item["name"] for item in items_with_ids}
        for result in response_dict["results"]:
            result["name"] = name_map[result["id"]]
            initial_results.append(result)
        # Extended flow: disease split -> DB rules -> adjudicate roles
        diseases_llm = await _split_diseases_with_llm(symptom)
        # Always include original symptom alongside split diseases
        diseases: List[str] = []
        if symptom and isinstance(symptom, str) and symptom.strip():
            diseases.append(symptom.strip())
        diseases.extend(diseases_llm)
        # Deduplicate while preserving order
        seen_d = set()
        diseases = [d for d in diseases if not (d.lower() in seen_d or seen_d.add(d.lower()))]
        print("_split_diseases_with_llm (combined with original): ", diseases)
        # Default to initial results if no DB configured or no diseases
        if not dsn_for_logging or not diseases:
            final_results = [MedicineResult(**r) for r in initial_results]
            await _log_event(
                dsn_for_logging,
                request_id,
                "final",
                {
                    "diseases": diseases,
                    "final_results": initial_results,
                    "note": "No DB/rules used (missing DSN or no diseases)",
                    "flags": {
                        "enable_db_disease_checker": _enable_db_checker,
                        "enable_protocol_rules": _enable_rules,
                        "force_protocol_rules": _force_rules,
                        "conservative_mode": _conservative,
                    },
                },
            )
            return {"results": final_results, "request_id": request_id, "changes": [], "changed": False, "change_details": []}
        # Connect to DB and gather rules
        pool: Optional[asyncpg.Pool] = None
        try:
            # Ensure min_size <= max_size to avoid runtime errors
            pool = await asyncpg.create_pool(dsn=dsn_for_logging, min_size=1, max_size=5)
            disease_matches: Dict[str, List[Dict]] = {}
            all_ids: List[int] = []
            for d in diseases:
                # Get top 3 diseases from database
                top3_matches = await _fetch_top3_clinical_diseases(pool, d)
                # print("Bệnh đơn lẻ: ", d)
                # print("_fetch_top3_clinical_diseases (raw): ", top3_matches)
                
                if enable_llm_validation:
                    # Validate diseases with LLM against original symptom
                    validated_matches = await _validate_diseases_with_llm(symptom, top3_matches, pool)
                    print("_validate_diseases_with_llm result: ", validated_matches)
                    disease_matches[d] = validated_matches
                    all_ids.extend([m["clinical_disease_id"] for m in validated_matches])
                else:
                    # Use raw top 3 diseases without LLM validation
                    disease_matches[d] = top3_matches
                    all_ids.extend([m["clinical_disease_id"] for m in top3_matches])
                    print("LLM validation disabled, using raw top 3 diseases")
                # print('=== all_ids: ', all_ids)
            rules: List[Dict] = []
            if _enable_rules:
                rules = await _fetch_protocol_rules_for_diseases(pool, all_ids)
                # print("_fetch_protocol_rules_for_diseases: ", rules)
            else:
                print("Protocol rules disabled by flag")
            # Run DB disease checker if enabled and available
            db_checker_results: Optional[Dict] = None
            if _enable_db_checker and _db_check_drug_list_by_multi_diseases_ilike:
                try:
                    print("symptom for db checker: ", symptom)
                    print("diseases for db checker: ", diseases)
                    db_checker_results = await _db_check_drug_list_by_multi_diseases_ilike(
                        diagnosis_text=symptom or "",
                        drug_names=[it["name"] for it in items_with_ids],
                        database_url=dsn_for_logging,
                        pre_split_diseases=diseases,  # Pass pre-split diseases to avoid duplicate LLM calls
                    )
                    print("===================db_checker_results: ", db_checker_results)
                except Exception as _e_chk:
                    print("DB disease checker error:", str(_e_chk))
                    db_checker_results = None
            else:
                print("DB disease checker disabled or unavailable")
        except Exception as e:
            print("Error on asyncpg.create_pool:", str(e))
        finally:
            if pool:
                await pool.close()
        # If we have rules and enabled, ask LLM to adjust roles per rules
        adjusted = await _adjudicate_roles_with_llm(items_with_ids, initial_results, diseases, disease_matches, rules) if (_enable_rules and rules) else initial_results
        print("adjusted: ", adjusted)
        # Build DB role map per input_name
        inputname_to_dbrole: Dict[str, Dict[str, Union[str, List[str]]]] = {}
        if _enable_db_checker and db_checker_results and isinstance(db_checker_results, dict):
            try:
                for entry in db_checker_results.get('results', []) or []:
                    name = cast(str, entry.get('input_name'))
                    role = cast(str, entry.get('role'))
                    related = entry.get('related_diseases') or []
                    inputname_to_dbrole[name] = {"role": role, "related_diseases": related}
            except Exception:
                inputname_to_dbrole = {}
        # Post-override logic (rules > db > llm)
        def _map_db_role_to_final(db_role: str) -> Optional[str]:
            if not db_role:
                return None
            lr = db_role.lower()
            if lr == 'treat':
                return 'main drug'
            if lr in {'support', 'prevent'}:
                return 'secondary drug'
            return None  # unrelated -> no override

        final_adjusted: List[Dict] = []
        for r in adjusted:
            role_before = r.get('role')
            category_ok = (r.get('category') == 'drug')
            validity_ok = (r.get('validity') == 'valid')
            new_role = role_before
            source = 'protocol db'
            # If rules were applied and forced, keep rule result
            if _enable_rules and rules and _force_rules:
                source = 'rule_forced'
            else:
                # Try DB override if eligible
                if category_ok and validity_ok and _enable_db_checker and inputname_to_dbrole:
                    nm = r.get('name')
                    dbinfo = inputname_to_dbrole.get(nm)
                    if dbinfo:
                        mapped = _map_db_role_to_final(cast(str, dbinfo.get('role')))
                        if mapped:
                            if _conservative:
                                # conservative: only upgrade to main drug when treat; support/prevent allowed since mapped is only main/secondary here
                                new_role = mapped
                                source = 'db_checker_conservative'
                            else:
                                new_role = mapped
                                source = 'db_checker'
            final_adjusted.append({**r, 'role': new_role, '_decision_source': source})
        final_results = [MedicineResult(**r) for r in adjusted]
        print("final_results: ", final_results)
        # Compute changes versus LLM output
        initial_map = {r["id"]: r for r in initial_results}
        changes: List[Dict] = []
        for r in final_adjusted:
            rid = r.get("id")
            before = initial_map.get(rid, {})
            diff: Dict[str, Dict[str, str]] = {}
            for field in ["category", "validity", "role", "explanation"]:
                bv = before.get(field)
                av = r.get(field)
                if bv != av:
                    diff[field] = {"before": bv, "after": av}
            if diff:
                changes.append({"id": rid, "changes": diff, "source": r.get('_decision_source')})
        # Log final adjudicated output (with diseases, matches, and rules)
        try:
            await _log_event(
                dsn_for_logging,
                request_id,
                "final",
                {
                    "diseases": diseases,
                    "disease_matches": disease_matches,
                    "rules": rules,
                    "db_checker_results": db_checker_results,
                    "final_results": final_adjusted,
                    "changed_count": len(changes),
                    "changes": changes,
                    "llm_validation_enabled": enable_llm_validation,
                    "flags": {
                        "enable_db_disease_checker": _enable_db_checker,
                        "enable_protocol_rules": _enable_rules,
                        "force_protocol_rules": _force_rules,
                        "conservative_mode": _conservative,
                    },
                },
            )
        except Exception as _e:
            print("log final error:", str(_e))
        return {"results": [MedicineResult(**r) for r in final_adjusted], "request_id": request_id, "changes": changes, "changed": len(changes) > 0, "change_details": changes}
        
    except Exception as e:
        print("Error in classify_with_gpt4:", str(e))