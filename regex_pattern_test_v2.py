import re
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from difflib import SequenceMatcher
from fuzzywuzzy import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sentence_transformers import SentenceTransformer
import pickle
import sqlite3
import logging

@dataclass
class Drug:
    id: int
    name: str
    generic_name: str
    brand_names: List[str]
    indication_text: str
    dosage_forms: List[str]
    active_ingredients: List[str]

@dataclass
class MatchResult:
    drug: Drug
    similarity_score: float
    disease_match_score: float
    confidence_score: float
    matched_text: str
    match_method: str

class DrugMatcher:
    def __init__(self, db_path: str, model_path: Optional[str] = None):
        self.db_path = db_path
        self.drugs_df = None
        self.tfidf_vectorizer = None
        self.drug_vectors = None
        self.sentence_model = None
        self.ml_model = None
        self.disease_synonyms = self._load_disease_synonyms()
        self._load_data()
        self._initialize_models()
        
    def _load_data(self):
        """Load drug data from hardcoded sample instead of DB"""
        sample_data = [
            {
                "id": 1,
                "name": "Paracetamol",
                "generic_name": "Paracetamol",
                "brand_names": "Panadol, Tylenol, Efferalgan",
                "indication_text": "Giảm đau, hạ sốt, điều trị đau đầu",
                "dosage_forms": "Viên nén, gói bột hòa tan",
                "active_ingredients": "Paracetamol 500mg"
            },
            {
                "id": 2,
                "name": "Ibuprofen",
                "generic_name": "Ibuprofen",
                "brand_names": "Advil, Motrin, Nurofen",
                "indication_text": "Giảm đau, kháng viêm, hạ sốt",
                "dosage_forms": "Viên nén, viên nang, hỗn dịch uống",
                "active_ingredients": "Ibuprofen 200mg"
            },
            {
                "id": 3,
                "name": "Metformin",
                "generic_name": "Metformin",
                "brand_names": "Glucophage, Fortamet, Riomet",
                "indication_text": "Điều trị bệnh tiểu đường type 2",
                "dosage_forms": "Viên nén, viên phóng thích chậm",
                "active_ingredients": "Metformin HCl 500mg"
            }
        ]
        
        self.drugs_df = pd.DataFrame(sample_data)
        
        # Preprocess drug names for better matching
        self.drugs_df['normalized_name'] = self.drugs_df['name'].apply(self._normalize_text)
        self.drugs_df['search_text'] = (
            self.drugs_df['name'] + ' ' + 
            self.drugs_df['generic_name'] + ' ' + 
            self.drugs_df['brand_names']
        ).apply(self._normalize_text)
        
        # Preprocess drug names for better matching
        self.drugs_df['normalized_name'] = self.drugs_df['name'].apply(self._normalize_text)
        self.drugs_df['search_text'] = (
            self.drugs_df['name'] + ' ' + 
            self.drugs_df['generic_name'] + ' ' + 
            self.drugs_df['brand_names']
        ).apply(self._normalize_text)
        
    def _initialize_models(self):
        """Initialize ML models and vectorizers"""
        # TF-IDF for drug name matching
        self.tfidf_vectorizer = TfidfVectorizer(
            ngram_range=(1, 3),
            max_features=10000,
            analyzer='char_wb'
        )
        self.drug_vectors = self.tfidf_vectorizer.fit_transform(
            self.drugs_df['search_text']
        )
        
        # Sentence transformer for semantic similarity
        try:
            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
        except:
            logging.warning("Could not load sentence transformer model")
            self.sentence_model = None
            
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching"""
        if pd.isna(text):
            return ""
        
        text = str(text).lower()
        # Remove Vietnamese accents
        text = self._remove_accents(text)
        # Remove special characters except spaces and letters
        text = re.sub(r'[^a-z0-9\s]', '', text)
        # Normalize spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
        
    def _remove_accents(self, text: str) -> str:
        """Remove Vietnamese accents"""
        accents = {
            'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
            'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
            'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
            'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
            'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
            'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
            'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
            'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
            'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
            'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
            'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
            'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
            'đ': 'd'
        }
        
        for accented, plain in accents.items():
            text = text.replace(accented, plain)
        return text
        
    def _load_disease_synonyms(self) -> Dict[str, List[str]]:
        """Load disease synonyms dictionary"""
        return {
            "đau đầu": ["đau đầu", "nhức đầu", "cephalgia", "headache", "đau nửa đầu"],
            "tiểu đường": ["tiểu đường", "đái tháo đường", "diabetes", "bệnh tiểu đường", "đường huyết"],
            "cao huyết áp": ["cao huyết áp", "tăng huyết áp", "hypertension", "huyết áp cao"],
            "viêm gan": ["viêm gan", "hepatitis", "gan nhiễm", "bệnh gan"],
            "hen suyễn": ["hen suyễn", "asthma", "khó thở", "co thắt phế quản"],
            "trầm cảm": ["trầm cảm", "depression", "u uất", "rối loạn tâm trạng"],
            "đau dạ dày": ["đau dạ dày", "viêm dạ dày", "gastritis", "loét dạ dày"]
        }
        
    def find_drug_candidates(self, input_drug: str, top_k: int = 10) -> List[Dict]:
        """Find drug candidates using multiple matching strategies"""
        normalized_input = self._normalize_text(input_drug)
        candidates = []
        
        # Strategy 1: Exact match
        exact_matches = self.drugs_df[
            self.drugs_df['normalized_name'].str.contains(normalized_input, na=False) |
            self.drugs_df['search_text'].str.contains(normalized_input, na=False)
        ]
        
        for _, drug in exact_matches.iterrows():
            candidates.append({
                'drug_id': drug['id'],
                'drug_data': drug,
                'similarity_score': 1.0,
                'match_method': 'exact'
            })
        
        # Strategy 2: Fuzzy matching
        if len(candidates) < top_k:
            drug_names = self.drugs_df['search_text'].tolist()
            fuzzy_matches = process.extract(
                normalized_input, 
                drug_names, 
                scorer=fuzz.token_sort_ratio,
                limit=top_k * 2
            )
            
            for match, score in fuzzy_matches:
                if score >= 60:  # Threshold
                    idx = drug_names.index(match)
                    drug = self.drugs_df.iloc[idx]
                    if drug['id'] not in [c['drug_id'] for c in candidates]:
                        candidates.append({
                            'drug_id': drug['id'],
                            'drug_data': drug,
                            'similarity_score': score / 100.0,
                            'match_method': 'fuzzy'
                        })
        
        # Strategy 3: TF-IDF similarity
        if len(candidates) < top_k:
            input_vector = self.tfidf_vectorizer.transform([normalized_input])
            similarities = cosine_similarity(input_vector, self.drug_vectors).flatten()
            
            top_indices = similarities.argsort()[-top_k:][::-1]
            for idx in top_indices:
                if similarities[idx] >= 0.1:  # Threshold
                    drug = self.drugs_df.iloc[idx]
                    if drug['id'] not in [c['drug_id'] for c in candidates]:
                        candidates.append({
                            'drug_id': drug['id'],
                            'drug_data': drug,
                            'similarity_score': similarities[idx],
                            'match_method': 'tfidf'
                        })
        
        # Sort by similarity score
        candidates.sort(key=lambda x: x['similarity_score'], reverse=True)
        return candidates[:top_k]
        
    def check_disease_indication(self, indication_text: str, target_disease: str, 
                               regex_patterns: List[str] = None) -> Dict:
        """Check if indication text mentions target disease"""
        if not indication_text:
            return {'match': False, 'score': 0.0, 'matched_text': '', 'method': 'none'}
        
        normalized_indication = self._normalize_text(indication_text)
        normalized_disease = self._normalize_text(target_disease)
        
        # Method 1: Direct string matching
        if normalized_disease in normalized_indication:
            return {
                'match': True,
                'score': 0.9,
                'matched_text': target_disease,
                'method': 'direct'
            }
        
        # Method 2: Synonym matching
        for canonical, synonyms in self.disease_synonyms.items():
            for synonym in synonyms:
                normalized_synonym = self._normalize_text(synonym)
                if (normalized_synonym in normalized_indication and 
                    normalized_disease in [self._normalize_text(s) for s in synonyms]):
                    return {
                        'match': True,
                        'score': 0.85,
                        'matched_text': synonym,
                        'method': 'synonym'
                    }
        
        # Method 3: Regex patterns
        if regex_patterns:
            for pattern in regex_patterns:
                try:
                    # Replace {disease} placeholder with actual disease name
                    formatted_pattern = pattern.replace('{disease}', normalized_disease)
                    match = re.search(formatted_pattern, normalized_indication, re.IGNORECASE)
                    if match:
                        return {
                            'match': True,
                            'score': 0.8,
                            'matched_text': match.group(),
                            'method': 'regex'
                        }
                except re.error:
                    logging.warning(f"Invalid regex pattern: {pattern}")
        
        # Method 4: Semantic similarity (if model available)
        if self.sentence_model:
            try:
                disease_embedding = self.sentence_model.encode([normalized_disease])
                indication_embedding = self.sentence_model.encode([normalized_indication])
                similarity = cosine_similarity(disease_embedding, indication_embedding)[0][0]
                
                if similarity >= 0.6:  # Threshold
                    return {
                        'match': True,
                        'score': similarity,
                        'matched_text': f"Semantic similarity: {similarity:.2f}",
                        'method': 'semantic'
                    }
            except Exception as e:
                logging.warning(f"Semantic similarity failed: {e}")
        
        return {'match': False, 'score': 0.0, 'matched_text': '', 'method': 'none'}
    
    def match_drug_disease(self, input_drug: str, target_disease: str, 
                          regex_patterns: List[str] = None, top_k: int = 5) -> List[MatchResult]:
        """Main method to match drug with disease indication"""
        # Step 1: Find drug candidates
        drug_candidates = self.find_drug_candidates(input_drug, top_k=top_k * 2)
        print(f"Found {len(drug_candidates)} drug candidates for '{input_drug}, cụ thể {drug_candidates}'")
        # Step 2: Check disease indication for each candidate
        results = []
        for candidate in drug_candidates:
            drug_data = candidate['drug_data']
            indication_check = self.check_disease_indication(
                drug_data['indication_text'],
                target_disease,
                regex_patterns
            )
            
            if indication_check['match']:
                # Calculate combined confidence score
                confidence = (
                    candidate['similarity_score'] * 0.6 +
                    indication_check['score'] * 0.4
                )
                
                drug_obj = Drug(
                    id=drug_data['id'],
                    name=drug_data['name'],
                    generic_name=drug_data['generic_name'],
                    brand_names=drug_data['brand_names'].split(',') if drug_data['brand_names'] else [],
                    indication_text=drug_data['indication_text'],
                    dosage_forms=drug_data['dosage_forms'].split(',') if drug_data['dosage_forms'] else [],
                    active_ingredients=drug_data['active_ingredients'].split(',') if drug_data['active_ingredients'] else []
                )
                
                result = MatchResult(
                    drug=drug_obj,
                    similarity_score=candidate['similarity_score'],
                    disease_match_score=indication_check['score'],
                    confidence_score=confidence,
                    matched_text=indication_check['matched_text'],
                    match_method=f"{candidate['match_method']}+{indication_check['method']}"
                )
                
                results.append(result)
        
        # Sort by confidence score
        results.sort(key=lambda x: x.confidence_score, reverse=True)
        return results[:top_k]

class MLDrugDiseaseClassifier:
    """Machine Learning approach for drug-disease matching"""
    
    def __init__(self):
        self.feature_extractor = None
        self.classifier = None
        self.is_trained = False
        
    def extract_features(self, drug_name: str, drug_indication: str, 
                        target_disease: str) -> np.ndarray:
        """Extract features for ML model"""
        features = []
        
        # Text similarity features
        drug_norm = self._normalize_text(drug_name)
        indication_norm = self._normalize_text(drug_indication)
        disease_norm = self._normalize_text(target_disease)
        
        # 1. String similarity features
        features.extend([
            fuzz.ratio(drug_norm, disease_norm) / 100.0,
            fuzz.partial_ratio(drug_norm, disease_norm) / 100.0,
            fuzz.token_sort_ratio(drug_norm, disease_norm) / 100.0,
            fuzz.token_set_ratio(drug_norm, disease_norm) / 100.0,
        ])
        
        # 2. Indication-disease similarity
        features.extend([
            fuzz.ratio(indication_norm, disease_norm) / 100.0,
            fuzz.partial_ratio(indication_norm, disease_norm) / 100.0,
            fuzz.token_sort_ratio(indication_norm, disease_norm) / 100.0,
            fuzz.token_set_ratio(indication_norm, disease_norm) / 100.0,
        ])
        
        # 3. Contains features
        features.extend([
            float(disease_norm in indication_norm),
            float(any(word in indication_norm for word in disease_norm.split())),
            len(set(disease_norm.split()) & set(indication_norm.split())) / max(len(disease_norm.split()), 1),
        ])
        
        # 4. Length features
        features.extend([
            len(drug_name),
            len(drug_indication),
            len(target_disease),
            len(drug_indication.split()),
        ])
        
        return np.array(features)
        
    def prepare_training_data(self, training_examples: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare training data from examples"""
        X = []
        y = []
        
        for example in training_examples:
            features = self.extract_features(
                example['drug_name'],
                example['drug_indication'], 
                example['target_disease']
            )
            X.append(features)
            y.append(example['label'])  # 1 for match, 0 for no match
            
        return np.array(X), np.array(y)
        
    def train(self, training_examples: List[Dict], model_type: str = 'rf'):
        """Train the ML model"""
        X, y = self.prepare_training_data(training_examples)
        
        if model_type == 'rf':
            self.classifier = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )
        elif model_type == 'lr':
            self.classifier = LogisticRegression(random_state=42)
        else:
            raise ValueError(f"Unknown model type: {model_type}")
            
        self.classifier.fit(X, y)
        self.is_trained = True
        
    def predict(self, drug_name: str, drug_indication: str, target_disease: str) -> Tuple[int, float]:
        """Predict if drug treats disease"""
        if not self.is_trained:
            raise ValueError("Model not trained yet")
            
        features = self.extract_features(drug_name, drug_indication, target_disease)
        prediction = self.classifier.predict([features])[0]
        probability = self.classifier.predict_proba([features])[0][1]  # Probability of positive class
        
        return prediction, probability
        
    def save_model(self, path: str):
        """Save trained model"""
        with open(path, 'wb') as f:
            pickle.dump({'classifier': self.classifier, 'is_trained': self.is_trained}, f)
            
    def load_model(self, path: str):
        """Load trained model"""
        with open(path, 'rb') as f:
            data = pickle.load(f)
            self.classifier = data['classifier']
            self.is_trained = data['is_trained']
            
    def _normalize_text(self, text: str) -> str:
        """Same normalization as main class"""
        if pd.isna(text):
            return ""
        return str(text).lower().strip()

# Example usage and testing
def create_sample_training_data() -> List[Dict]:
    """Create sample training data for ML model"""
    return [
        {
            'drug_name': 'Paracetamol',
            'drug_indication': 'Paracetamol có tác dụng gì? Thuốc Paracetamol 500mg được chỉ định điều trị trong các trường hợp sau: Các cơn đau từ nhẹ đến trung bình bao gồm đau đầu, đau nửa đầu, đau thần kinh đau răng, đau họng, đau do hành kinh, đau nhức. Giảm triệu chứng đau nhức do thấp khớp, cảm cúm, cảm sốt và cảm lạnh.',
            'target_disease': 'đau nửa đầu mãn tinh',
            'label': 1
        },
        {
            'drug_name': 'Aspirin',
            'drug_indication': 'Giảm đau, chống viêm, phòng ngừa đột quỵ',
            'target_disease': 'tiểu đường',
            'label': 0
        },
        {
            'drug_name': 'Metformin',
            'drug_indication': 'Điều trị bệnh tiểu đường type 2',
            'target_disease': 'tiểu đường',
            'label': 1
        },
        # Add more training examples...
    ]

def main():
    # Initialize the system
    matcher = DrugMatcher('drugs.db')
    
    # Example usage
    input_drug = "paracetamol 500mg"
    target_disease = "đau đầu"
    regex_patterns = [
        r"điều trị.*?{disease}",
        r"chỉ định.*?{disease}",
        r"{disease}.*?triệu chứng"
    ]
    
    results = matcher.match_drug_disease(
        input_drug=input_drug,
        target_disease=target_disease,
        regex_patterns=regex_patterns,
        top_k=5
    )
    
    print(f"Results for '{input_drug}' treating '{target_disease}':")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result.drug.name}")
        print(f"   Confidence: {result.confidence_score:.2f}")
        print(f"   Drug similarity: {result.similarity_score:.2f}")
        print(f"   Disease match: {result.disease_match_score:.2f}")
        print(f"   Method: {result.match_method}")
        print(f"   Matched text: {result.matched_text}")
    
    # ML approach example
    ml_classifier = MLDrugDiseaseClassifier()
    training_data = create_sample_training_data()
    ml_classifier.train(training_data)
    
    # Test ML prediction
    prediction, probability = ml_classifier.predict(
        'Paracetamol 500mg',
        'Giảm đau, hạ sốt, điều trị nhức đầu',
        'đau đầu'
    )
    
    print(f"\nML Prediction: {prediction}, Probability: {probability:.2f}")

if __name__ == "__main__":
    main()