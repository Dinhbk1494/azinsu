from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union
from openai import AzureOpenAI
from fastapi import HTTPException
import os
from dotenv import load_dotenv
import uuid
import json

load_dotenv()

# Configure Azure OpenAI
azure_api_key = os.getenv("AZURE_API_KEY")
openai_client = AzureOpenAI(
    api_version="2024-12-01-preview",
    azure_endpoint="https://admin-m9kv2jak-eastus2.cognitiveservices.azure.com/",
    api_key=azure_api_key
)

class MedicineItem(BaseModel):
    id: str = Field(..., description="Unique identifier for the medicine")
    name: str = Field(..., description="Name of the medicine")

class MedicineRequest(BaseModel):
    items: Union[List[str], List[MedicineItem]] = Field(
        ..., 
        description="Danh sách tên thuốc được kê đơn. Có thể là list of strings hoặc list of objects với id và name",
        examples=[
            # Example 1: List of strings
            [
                "Paracetamol 500mg",
                "Amoxicillin 500mg",
                "Cetirizine 10mg",
                "Vitamin C 1000mg"
            ],
            # Example 2: List of objects with id and name
            [
                {"id": "a1f2c3", "name": "Paracetamol 500mg"},
                {"id": "b4d5e6", "name": "Amoxicillin 500mg"},
                {"id": "c7g8h9", "name": "Cetirizine 10mg"},
                {"id": "d0i1j2", "name": "Vitamin C 1000mg"}
            ]
        ]
    )
    symptom: Optional[str] = Field(
        None, 
        description="Kết luận/chẩn đoán của bác sĩ",
        example="Viêm họng cấp tính kèm sốt nhẹ. Có dấu hiệu dị ứng theo mùa."
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

    class Config:
        from_attributes = True

def validate_classification_response(response_text: str, input_data: dict) -> tuple[bool, str]:
    """
    Validate the classification response using LLM
    Args:
        response_text: The response to validate
        input_data: Dictionary containing items with UUIDs and symptom
    Returns: (is_valid: bool, validated_response: str)
    """
    validation_prompt = f"""
    Bạn là chuyên gia kiểm tra và xác thực kết quả phân loại thuốc. Hãy kiểm tra kết quả phân loại sau đây:

    Input data:
    {json.dumps(input_data, indent=2, ensure_ascii=False)}
    
    Kết quả phân loại:
    {response_text}

    Hãy kiểm tra các tiêu chí sau:
    1. Format JSON có hợp lệ không?
    2. Mỗi item có đầy đủ các trường: id, category, validity, role, explanation không?
    3. Số lượng thuốc trong kết quả phải bằng số lượng thuốc trong input?
    3. Tất cả các ID trong kết quả có khớp với ID trong input không?
    4. Đối với "category" là "drug":
        a. Với các thuốc có "role" là "secondary drug", các thuốc này phải:
            - Thuốc làm giảm, ngăn ngừa tác dụng phụ của thuốc chính
            - Vitamin ghi rõ liều lượng
            Chú ý: Nếu thuốc có hỗ trợ bệnh hay triệu chứng, thì được coi là 'main drug'
        b. Với các thuốc có "role" là "main drug", các thuốc này phải:
            - Thuốc điều trị, hỗ trợ bệnh, triệu chứng
            - Thuốc Đông y cụ thể hoặc một bài thuốc cổ truyền (ví dụ: Ngưu tất, Độc hoạt tang ký sinh, Boganic, ...)
    
    Với mỗi thuốc, hãy đối chiếu với symptom và tên thuốc trong input để đảm bảo phân loại chính xác
    Nếu tất cả đều đúng, trả về:
    {{"is_valid": true}}

    Nếu có lỗi hoặc cần sửa, trả về:
    {{"is_valid": false, "corrected_response": <kết quả đã sửa>, "explanation": "Giải thích lý do sửa"}}

    CHÚ Ý: 
    - Nếu cần sửa, hãy giữ nguyên format JSON và các ID (nếu đã hợp lý), chỉ sửa 'category', 'validity', 'role' và 'explanation' nếu cần.
    - Đảm bảo mỗi ID trong input đều được phân loại và xuất hiện trong kết quả.
    - Đảm bảo giải thích (explanation) phù hợp với tên thuốc và symptom.
    """

    try:
        messages = [
            {"role": "system", "content": "Bạn là chuyên gia kiểm tra và xác thực kết quả phân loại thuốc."},
            {"role": "user", "content": validation_prompt}
        ]
        
        validation_response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0
        )
        
        validation_result = json.loads(validation_response.choices[0].message.content)
        print("Validation result:", validation_result)
        
        if validation_result.get("is_valid"):
            return True, response_text
        else:
            if "explanation" in validation_result:
                print("Validation explanation:", validation_result["explanation"])
            
            # If corrected_response is a dict, convert it to JSON string
            corrected_response = validation_result.get("corrected_response", response_text)
            if isinstance(corrected_response, dict):
                corrected_response = json.dumps(corrected_response)
            
            return False, corrected_response
            
    except Exception as e:
        print("Error in validation:", str(e))
        return True, response_text  # Return original response if validation fails

def classify_with_gpt4(items: Union[List[str], List[MedicineItem]], symptom: str = None) -> Dict[str, list]:
    """
    Classify items using Azure OpenAI GPT-4 API with enhanced examples
    Returns dictionary with classifications and explanations
    """
    # Handle different input formats and prepare items with IDs
    if isinstance(items[0], str):
        # If input is list of strings, generate UUIDs
        items_with_ids = [{"id": str(uuid.uuid4())[:6], "name": item} for item in items]
    else:
        # If input is list of objects, use provided IDs
        items_with_ids = [{"id": item.id, "name": item.name} for item in items]
    
    system = """
    Bạn là chuyên gia dược phẩm với nhiệm vụ phân loại các mục được cung cấp và giải thích chi tiết về mỗi phân loại.
    
    Phân loại theo các tiêu chí sau. Bạn LUÔN LUÔN thực hiện các nhiệm vụ cụ thể rõ ràng sau đây, ƯU TIÊN các định nghĩa và ví dụ trong prompt này hơn bất kỳ kiến thức nào khác:

    1. category: 
        - "drug": Thuốc điều trị bệnh, Vitamin/khoáng/Thuốc đông y chất bao gồm:
            + Thuốc điều trị bệnh cụ thể (kháng sinh, giảm đau, v.v.)
            + Vitamin/khoáng chất khi:
                * Điều trị bệnh lý cụ thể theo chẩn đoán
                * Có liều lượng điều trị cụ thể (VD: Vitamin C 1000mg)
                * Ngăn ngừa tác dụng phụ của thuốc khác
            + Nếu tên thuốc là một vị thuốc Đông y cụ thể hoặc một bài thuốc cổ truyền (ví dụ: Ngưu tất, Độc hoạt tang ký sinh, Boganic) VÀ có "symptom" thì được coi là thuốc
        - "nodrug": Không phải thuốc
            
    2. validity: "valid" hoặc "invalid" dựa trên chẩn đoán
        - "valid": Phù hợp với chẩn đoán hoặc thuốc hỗ trợ, giảm tác dụng phụ thuốc chính
        - "invalid": Không phù hợp với chẩn đoán hoặc không phải là thuốc hỗ trợ, hay không giảm tác dụng phụ thuốc chính
        - Mặc định "valid" nếu không có chẩn đoán
        
    3. role: Phân loại vai trò của item
        Nếu category là "drug":
            - "main drug" được định nghĩa như sau:
                * Thuốc ĐIỀU TRỊ, HỖ TRỢ hay CẢI THIỆN bệnh/triệu chứng của ít nhất 1 bệnh trong 'symptom' (một chẩn đoán có thể có nhiều bệnh)
                * Nếu thuốc là vitamin kết hợp với loại khác (ví dụ: Nhôm hydroxyd + Magnesium hydroxide) thì sẽ coi là "main drug"
                * Các thuốc *kháng sinh*, *kháng viêm*, *giảm viêm*, *giảm đau hạ sốt*, *thuốc kháng dị ứng* đều là "main drug"
                * Nếu vitamin hay thành phần chính là vitamin, nhưng chẩn đoán bệnh có liên quan thiếu vitamin hay điện giải thì lúc này đây được coi là "main drug"
            - "secondary drug" được định nghĩa như sau:
                * Thuốc làm giảm tác dụng phụ của thuốc chính
                * Vitamin không ghi rõ liều lượng
        
        Nếu category là "nodrug":
            - "supplement": Thực phẩm chức năng, vitamin bổ sung
            - "medical supplies": Vật tư y tế
            - "medical equipment": Thiết bị y tế
            - "cosmeceuticals": Mỹ phẩm có tác dụng điều trị
            - "other": Không xác định được
        
    4. explanation:
        Giải thích ngắn gọn lý do phân loại, tập trung vào:
            - Tác dụng chính của thuốc/sản phẩm
            - Mối liên quan với chẩn đoán
            - Lý do phân loại vai trò

    Lưu ý đặc biệt:
        - Tuyệt đối phân loại theo các định nghĩa của tôi
        - Đối với 'drug', hãy dựa vào CHỈ ĐỊNH THUỐC để quyết định là 'main drug' hay 'secondary drug'
        - Tất cả các loại thuốc được kê có xu hướng đều là 'main drug', do đó nếu không có chứng cứ rõ ràng một loại thuốc nào đó thuộc 'secondary drug, thì hãy coi nó là 'main drug'.
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
        { "id": "d4e5f6", "name": "Vitamin C 1000mg" },
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
          "id": "d4e5f6",
          "category": "drug",
          "validity": "valid",
          "role": "secondary drug",
          "explanation": "Vitamin C là thực phẩm bổ sung, nhưng có liều lượng cụ thể nên có thể coi là thuốc hỗ trợ."
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
        "symptom": symptom if symptom else "Chưa có thông tin chi tiết về kết quả khám bệnh"
    }
    print("Input data: ", input_data)
    
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": str(input_data)}
        ]
        
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0
        )
        
        # Get response and parse JSON
        response_text = response.choices[0].message.content
        print("Initial response_text: ", response_text)
        
        # Validate and potentially correct the response
        is_valid, validated_response = validate_classification_response(response_text, input_data)
        print("Validation result - is_valid:", is_valid)
        print("Validated response:", validated_response)
        
        # Convert response to Python dict
        response_dict = json.loads(validated_response)
        
        # Create final response with both id and name
        final_results = []
        name_map = {item["id"]: item["name"] for item in items_with_ids}
        
        for result in response_dict["results"]:
            result["name"] = name_map[result["id"]]
            final_results.append(MedicineResult(**result))
        
        print("final_results: ", final_results)
        return {"results": final_results}
        
    except Exception as e:
        print("Error in classify_with_gpt4:", str(e))
        raise HTTPException(status_code=500, detail=f"Azure OpenAI Classification error: {str(e)}")