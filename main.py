from fastapi import FastAPI, FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import uvicorn
from multi_claim_classifier import MultiClaimClassifier
import medicine_classifier as med_classifier
import medicine_classifier_v2 as med_classifier_v2
import medicine_classifier_v3_test as med_classifier_v3_test
import os
from dotenv import load_dotenv
import nest_asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Optional
from tavily import TavilyClient
import multi_claim_classifier_v2

# Enable nested event loops
nest_asyncio.apply()

# Load environment variables
load_dotenv()

azure_api_key = os.getenv("AZURE_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


app = FastAPI(
    title="Insurance Claim API",
    description="API for classifying, searching and evaluating insurance claims",
    version="1.0.0"
)

class DrugRequest(BaseModel):
    drug_names: List[str] = Field(
        ...,
        description="Danh sách tên thuốc",
        example=[
            "Paracetamol 500mg",
            "Amoxicillin",
            "Losartan",
            "Metformin 850mg",
            "Atorvastatin"
        ]
    )

class DrugInfo(BaseModel):
    drug_name: str
    url: Optional[List[str]] = None
    summary: Optional[str] = None
    text: Optional[str] = None

class ClaimInput(BaseModel):
    claim_id: str = Field(..., description="Unique identifier for the claim", example="CLAIM001")
    service: str = Field(..., description="Type of service", example="Khám nội tổng quát")
    description: str = Field(..., description="Detailed description of the service", example="Khám tổng quát định kỳ")
    amount: float = Field(..., description="Claim amount in VND", example=1500000.0)

    class Config:
        json_schema_extra = {  # Updated from schema_extra to json_schema_extra for Pydantic V2
            "example": {
                "claim_id": "CLAIM001",
                "service": "Khám nội tổng quát",
                "description": "Khám tổng quát định kỳ",
                "amount": 1500000.0
            }
        }

class ClassificationRequest(BaseModel):
    claims: List[ClaimInput] = Field(
        ...,
        description="List of claims to classify",
        example=[
            {
                "claim_id": "CLAIM001",
                "service": "Khám nội tổng quát",
                "description": "Khám tổng quát định kỳ",
                "amount": 1500000.0
            },
            {
                "claim_id": "CLAIM002",
                "service": "Xét nghiệm máu",
                "description": "Xét nghiệm công thức máu",
                "amount": 800000.0
            }
        ]
    )
    benefits_text: str = Field(
        ...,
        description="Benefits description text for classification",
        example="""
            1.1 Quyền lợi khám tổng quát
            1.2 Quyền lợi điều trị nội trú
            1.3 Quyền lợi điều trị ngoại trú
            1.4 Quyền lợi nha khoa
        """
    )

class ClassificationRequest_thaisan(BaseModel):
    claim_info: Dict = Field(
        ...,
        description="Benefits description text for classification",
        example={
    "primary_diagnosis_code": "O80",
    "secondary_diagnosis_codes": [],
    "admission_reason": "Sinh thường, thai 39 tuần",
    "medical_history": "Không có tiền sử bệnh",
    "clinic_name": "Bệnh viện Phụ sản",
    "retail_pharmacy": "Nhà thuốc Long Châu",
    "outpatient_department": "Khoa Sản"
  }
    )
    claims: List[ClaimInput] = Field(
        ...,
        description="List of claims to classify Thai San",
        example=[
            {
                "claim_id": "CLAIM001",
                "service": "Khám nội tổng quát",
                "description": "Khám tổng quát định kỳ",
                "amount": 1500000.0
            },
            {
                "claim_id": "CLAIM002",
                "service": "Xét nghiệm máu",
                "description": "Xét nghiệm công thức máu",
                "amount": 800000.0
            }
        ]
    )
    benefits_text: str = Field(
        ...,
        description="Benefits description text for classification",
        example="""
            1.1 Quyền lợi khám tổng quát
            1.2 Quyền lợi điều trị nội trú
            1.3 Quyền lợi điều trị ngoại trú
            1.4 Quyền lợi nha khoa
        """
    )

class BenefitItem(BaseModel):
    id: str = Field(..., description="Benefit ID", example="2.2.1")
    description: str = Field(..., description="Benefit description", example="Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa")

class ClassificationRequest_ngoaitru(BaseModel):
    claim_info: Dict = Field(
        ...,
        description="General information about the outpatient claim event",
        example={
            "primary_diagnosis_code": "J02.9", # Ví dụ: Viêm họng cấp, không xác định
            "secondary_diagnosis_codes": ["R05"], # Ví dụ: Ho
            "admission_reason": "Khám do ho, đau họng", # Lý do khám bệnh
            "medical_history": "Không có bệnh lý nền đặc biệt",
            "clinic_name": "Phòng khám đa khoa An Sinh",
            "retail_pharmacy": "Nhà thuốc An Khang", # Hoặc "Nhà thuốc Long Châu" để test trường hợp khác
            "outpatient_department": "Khoa Tai Mũi Họng",
            "next_treatment_plan": "Tái khám sau 5 ngày nếu không đỡ",
            "document_type": "Hóa đơn bán lẻ" # Hoặc "Phiếu thu"
        }
    )
    claims: List[ClaimInput] = Field(
        ...,
        description="List of individual claim items for outpatient classification",
        example=[
            {
                "claim_id": "NGOAITRU001",
                "service": "Khám chuyên khoa TMH",
                "description": "Phí khám bệnh Tai Mũi Họng với bác sĩ chuyên khoa",
                "amount": 250000.0
            },
            {
                "claim_id": "NGOAITRU002",
                "service": "Thuốc Amoxicillin 500mg",
                "description": "Thuốc Amoxicillin 500mg - 2 vỉ",
                "amount": 120000.0
            },
            {
                "claim_id": "NGOAITRU003",
                "service": "Nước muối sinh lý",
                "description": "Chai nước muối sinh lý Natriclorid 0.9% 500ml",
                "amount": 15000.0
            },
            {
                "claim_id": "NGOAITRU004",
                "service": "Cạo vôi răng",
                "description": "Lấy cao răng và đánh bóng hai hàm",
                "amount": 300000.0
            }
        ]
    )
    benefits_text: str = Field(
        ...,
        description="Benefits description text for outpatient classification, containing benefit codes and their names",
        example="""2.2.1 Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa
2.2.1.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)
2.2.1.2 Phòng khám tư có dấu nhưng không có hóa đơn tài chính (hoạt động hợp pháp)
2.2.1.3 Có chẩn đoán bệnh nhưng chưa cần điều trị (chưa có đơn thuốc hoặc chưa thực hiện điều trị theo chỉ định)
2.2.1.4 Phòng khám tư không có hóa đơn tài chính & không dấu (Điều khoản này áp dụng cho phòng khám bác sỹ tư có giấy phép hành nghề nhưng không có đăng ký kinh doanh)
2.2.1.5 Rửa mũi xoang tại bệnh viện
2.2.1.6 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể
2.2.1.7 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu
2.2.2 Quyền lợi răng
2.2.2.1 Điều trị viêm lợi bằng việc lấy cao răng
2.2.3 Vật lý trị liệu
2.2.5 Khám thai định kỳ
2.2.6 Chi phí/lần khám nếu hồ sơ bồi thường có mua thuốc tại hệ thống chuỗi nhà thuốc FPT Long Châu
2.2.6.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)
2.2.6.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu
2.2.6.3 Rửa mũi xoang tại bệnh viện
2.2.6.4 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể
2.2.7 Khám tại phòng khám của FPT
2.2.8 Điều khoản bảo hiểm cho bệnh nghề nghiệp
2.2.9 Điều khoản bảo hiểm chi phí Lọc thẩm tách
2.2.10 Điều khoản bảo hiểm chi phí HIV/AIDS"""
    )

class ClassificationRequest_ngoaitru_v2(BaseModel):
    claim_info: Dict = Field(
        ...,
        description="General information about the outpatient claim event",
        example={
            "primary_diagnosis_code": "J02.9", # Ví dụ: Viêm họng cấp, không xác định
            "secondary_diagnosis_codes": ["R05"], # Ví dụ: Ho
            "admission_reason": "Khám do ho, đau họng", # Lý do khám bệnh
            "medical_history": "Không có bệnh lý nền đặc biệt",
            "clinic_name": "Phòng khám đa khoa An Sinh",
            "retail_pharmacy": "Nhà thuốc An Khang", # Hoặc "Nhà thuốc Long Châu" để test trường hợp khác
            "outpatient_department": "Khoa Tai Mũi Họng",
            "next_treatment_plan": "Tái khám sau 5 ngày nếu không đỡ",
            "document_type": "Hóa đơn bán lẻ" # Hoặc "Phiếu thu"
        }
    )
    claims: List[ClaimInput] = Field(
        ...,
        description="List of individual claim items for outpatient classification",
        example=[
            {
                "claim_id": "NGOAITRU001",
                "service": "Khám chuyên khoa TMH",
                "description": "Phí khám bệnh Tai Mũi Họng với bác sĩ chuyên khoa",
                "amount": 250000.0
            },
            {
                "claim_id": "NGOAITRU002",
                "service": "Thuốc Amoxicillin 500mg",
                "description": "Thuốc Amoxicillin 500mg - 2 vỉ",
                "amount": 120000.0
            }
        ]
    )
    benefits_text: List[BenefitItem] = Field(
        ...,
        description="List of benefit items with their IDs and descriptions",
        example=[
            {
                "id": "2.2.1",
                "description": "Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa"
            },
            {
                "id": "2.2.1.1",
                "description": "Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)"
            }
        ]
    )

@app.post("/medicine_classify/", response_model=med_classifier.MedicineResponse)
async def classify_medicines(request: med_classifier.MedicineRequest):
    """
    Endpoint to classify list of medicines/supplements
    """
    if not request.items:
        raise HTTPException(status_code=400, detail="No items provided")
    
    try:
        classifications = med_classifier.classify_with_gpt4(request.items, request.symptom)
        return med_classifier.MedicineResponse(classifications=classifications)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/medicine_classify_v2/", response_model=med_classifier_v2.MedicineResponse)
async def classify_medicines_v2(request: med_classifier_v2.MedicineRequest):
    """
    Test endpoint to classify list of medicines/supplements using the test classifier
    """
    if not request.items:
        raise HTTPException(status_code=400, detail="No items provided")
    
    try:
        result = await med_classifier_v2.classify_with_gpt4(request.items, request.symptom, request.request_id)
        # Convert to MedicineResponse model
        return med_classifier_v2.MedicineResponse(**result)

    except Exception as e:
        print("Error in classify_medicines_v2:", str(e))
        raise HTTPException(status_code=500, detail=f"Classification error: {str(e)}")

@app.post("/medicine_classify_v3_test/", response_model=med_classifier_v3_test.MedicineResponse)
async def classify_medicines_v2(request: med_classifier_v3_test.MedicineRequest):
    """
    Test endpoint to classify list of medicines/supplements using the test classifier
    """
    if not request.items:
        raise HTTPException(status_code=400, detail="No items provided")
    
    try:
        result = await med_classifier_v3_test.classify_with_gpt4(request.items, request.symptom, request.request_id)
        # Convert to MedicineResponse model
        return med_classifier_v3_test.MedicineResponse(**result)

    except Exception as e:
        print("Error in classify_medicines_v3_test:", str(e))
        raise HTTPException(status_code=500, detail=f"Classification error: {str(e)}")

@app.post("/classify", 
    response_model=Any,
    description="Classify insurance claims using multiple LLM AI models",
    response_description="Classification results"
)
async def classify_claims(request: ClassificationRequest):
    try:
        # Convert Pydantic models to dictionaries
        claims = [claim.dict() for claim in request.claims]
        
        # Get API keys from environment variables
        if not azure_api_key or not gemini_api_key:
            raise HTTPException(
                status_code=500,
                detail="API keys not configured. Please check environment variables."
            )
        
        classifier = MultiClaimClassifier(
            azure_api_key=azure_api_key,  # Updated to use azure_api_key
            gemini_api_key=gemini_api_key
        )
        
        results = await classifier.classify_claims(claims, request.benefits_text)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/classify_ngoaitru", 
    response_model=Any,
    description="Classify insurance claims 'Ngoai tru' using multiple LLM AI models",
    response_description="'Ngoai tru' results"
)
async def classify_claims_ngoaitru(request: ClassificationRequest_ngoaitru):
    try:
        # Convert Pydantic models to dictionaries
        claims = [claim.dict() for claim in request.claims]
        
        # Get API keys from environment variables
        if not azure_api_key or not gemini_api_key:
            raise HTTPException(
                status_code=500,
                detail="API keys not configured. Please check environment variables."
            )
        
        classifier = MultiClaimClassifier(
            azure_api_key=azure_api_key,  # Updated to use azure_api_key
            gemini_api_key=gemini_api_key
        )
        
        results = await classifier.classify_claims_ngoaitru(request.claim_info, claims, request.benefits_text)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/classify_ngoaitru_v2", 
    response_model=Any,
    description="Classify insurance claims 'Ngoai tru' using multiple LLM AI models (Version 2)",
    response_description="'Ngoai tru' results"
)
async def classify_claims_ngoaitru_v2(request: ClassificationRequest_ngoaitru_v2):
    try:
        # Convert Pydantic models to dictionaries
        claims = [claim.dict() for claim in request.claims]
        benefits_text = [benefit.dict() for benefit in request.benefits_text]
        
        # Get API keys from environment variables
        if not azure_api_key or not gemini_api_key:
            raise HTTPException(
                status_code=500,
                detail="API keys not configured. Please check environment variables."
            )
        
        classifier = multi_claim_classifier_v2.MultiClaimClassifierV2(
            azure_api_key=azure_api_key,
            gemini_api_key=gemini_api_key
        )
        
        # Pass benefits_text directly without transformation
        results = await classifier.classify_claims_ngoaitru(request.claim_info, claims, benefits_text)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/classify_thaisan", 
    response_model=Any,
    description="Classify insurance claims 'Thai San' using multiple LLM AI models",
    response_description="'Thai San' results"
)
async def classify_claims_thaisan(request: ClassificationRequest_thaisan):
    try:
        # Convert Pydantic models to dictionaries
        claims = [claim.dict() for claim in request.claims]
        
        # Get API keys from environment variables
        if not azure_api_key or not gemini_api_key:
            raise HTTPException(
                status_code=500,
                detail="API keys not configured. Please check environment variables."
            )
        
        classifier = MultiClaimClassifier(
            azure_api_key=azure_api_key,  # Updated to use azure_api_key
            gemini_api_key=gemini_api_key
        )
        
        results = await classifier.classify_claims_thaisan(request.claim_info, claims, request.benefits_text)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# TRA CỨU THUỐC
@app.post("/extract_drug_info", response_model=List[DrugInfo])
async def extract_drug_info(request: DrugRequest):
    results = []
    
    for drug_name in request.drug_names:
        try:
            # Thực hiện tìm kiếm với Tavily API
            search_result = tavily.search(
                query=f"tìm công dụng của thuốc: {drug_name}",
                max_results=3,
                include_answer="advanced",
                include_raw_content=True,
            )
            
            if search_result and search_result.get('results'):
                # Lấy kết quả đầu tiên có score cao nhất
                general_result = search_result['answer']
                all_urls = [res['url'] for res in search_result['results'] if res.get('url')]
                
                formatted_content_parts = []
                for idx, res in enumerate(search_result['results'], 1):
                    if res.get('content'):
                        content_part = f"Theo như đường link {res['url']}, chúng ta có thông tin như sau:\n"
                        content_part += f"{res['content']}\n"
                        if res.get('raw_content'):
                            content_part += f"Thông tin chi tiết:\n{res['raw_content']}\n"
                        formatted_content_parts.append(content_part)
                
                full_content = "\n\n".join(formatted_content_parts)
                
                results.append(DrugInfo(
                    drug_name=drug_name,
                    url=all_urls,
                    summary=general_result,
                    text=full_content
                ))
            else:
                results.append(DrugInfo(drug_name=drug_name))
                
        except Exception as e:
            print(f"Error processing drug {drug_name}: {str(e)}")
            results.append(DrugInfo(drug_name=drug_name))
            
    return results

@app.get("/health",
    description="Check API health status",
    response_description="Returns healthy status if API is running"
)
async def health_check():
    return {"status": "healthy", "message": "API is running"}



if __name__ == "__main__":
    # Configure uvicorn logging
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = "%(asctime)s - %(levelname)s - %(message)s"
    uvicorn.run(app, host="0.0.0.0", port=8000)