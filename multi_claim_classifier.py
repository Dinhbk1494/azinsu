from typing import List, Dict, Optional, Any, Union
import asyncio
import os
import google.generativeai as genai
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
import json
import re
from collections import defaultdict

def create_claim_item(claim_id: str, service: str, description: str, amount: float, benefit_id: dict = None) -> dict:
    """Factory function to create a claim item dictionary"""
    return {
        "claim_id": claim_id,
        "service": service,
        "description": description,
        "amount": amount,
        "benefit_id": benefit_id or {}
    }

def clean_benefit_id(benefit_id: str) -> str:
    """Extract just the numeric ID from benefit string"""
    if not benefit_id or benefit_id.lower() == 'none':
        return None
    match = re.match(r'^(\d+(?:\.\d+)?)', benefit_id)
    return match.group(1) if match else benefit_id

def create_detailed_prompt(claims: List[dict], benefits_text: str) -> str:
    """Create detailed prompt for claim classification"""
    claims_text = "\n".join([
        f"- ID: {claim['claim_id']}\n"
        f"  Loại dịch vụ: {claim['service']}\n"
        f"  Tên dịch vụ: {claim['description']}\n"
        f"  Số tiền: {claim['amount']:,.2f} VND"
        for claim in claims
    ])

    return f"""Hãy phân loại mỗi claim vào benefits phù hợp nhất.
Chú ý 1: Thuốc chính là thuốc kê toa.
Chú ý 2: Nếu không chú thích gì đặc biệt, chúng ta sẽ hiểu là cơ sở y tế/phòng khám có hóa đơn và đã có kết luận bệnh cụ thể rồi.
Chú ý 3: Nếu không nói rõ mua thuốc tại nhà thuốc 'Long Châu', thì coi là mua tại nơi khác.
Benefits list:
{benefits_text}

Default assumption: If no additional note is provided for a claim, it is understood that specific disease information or treatment instructions have been given.

Claims to classify:
{claims_text}

IMPORTANT: In your response:
1. Use EXACTLY the claim_id from input
2. Return benefit_id as plain numbers (e.g. "1.9"), corresponding to the information in 'Benefits list' or "Unknown"
3. Include confidence score (0-1)

Return format:
[
    {{
        "claim_id": "claim ID from input",
        "benefit_id": "just numbers like 1.9 or Unknown",
        "confidence": 0.95
    }},
    ...
]

Example correct format:
[
    {{
        "claim_id": "CLAIM001",
        "benefit_id": "1.2.1.1",
        "confidence": 0.99
    }}
]
"""


def create_detailed_prompt_thaisan():
    """Prompt tối ưu để phân loại chính xác quyền lợi Thai sản."""
    return """Bạn là chuyên viên phân loại quyền lợi Thai sản.

Nhiệm vụ duy nhất của bạn là chọn benefit_id CHI TIẾT NHẤT (mã dài nhất có thể) phù hợp với mỗi chi phí được liệt kê.

Tuy nhiên, để làm chính xác điều này, bạn phải làm theo đúng trình tự logic như sau:

[ BƯỚC 1 - KIỂM TRA NỘI TRONG 'benefits_text' ] 
Trường hợp 1: Thông tin 'benefits_text' bị rỗng:
    LUÔN LUÔN gán "benefit_id": "Unknown" cho tất cả claims.
Trường hợp 2: Có ID quyền lợi (benefit_id) nhưng thiếu đầy đủ chú thích rõ ràng giải thích quyền lợi:
    Xem như mã này KHÔNG hợp lệ. Không được chọn mã này và chọn quyền lợi khác thay thế hoặc ghi Unknown nếu không tìm được mã hợp lệ khác.
Trường hợp 3 Description mô tả claim khó hiểu, thiếu thông tin hoặc sai chính tả nghiêm trọng:
    Không cố đoán suy diễn. Hãy chọn nhóm cha (bước 2 nếu rõ ràng) hoặc Unknown (ưu tiên Unknown nếu vẫn không chắc).

[ BƯỚC 2 - CHỌN NHÓM QUYỀN LỢI CHA - là bước TRUNG GIAN bắt buộc ]
- Dựa vào thông tin dưới đây để chọn quyền lợi cha chính xác nhất:
    + Tử vong: ICD O95, O96, O97
    + Biến chứng thai sản: O00-O08, O10-O16, O20-O29, O30-O48, O60-O75, O85-O92, O94, O98, O99
    + Sinh mổ theo chỉ định: O82, O84.2, O84.8, O84.9 (với thông tin: chỉ định sinh mổ hoặc có lịch sử mổ cũ)
    + Sinh mổ không chỉ định: O82, O84.2, O84.8, O84.9 (không có thông tin rõ ràng về chỉ định ở trên)
    + Sinh thường: O80, O81, O83, O84.0, O84.1
    + Khám thai định kỳ: khám, siêu âm thai, theo dõi thai trước khi sinh

[ BƯỚC 3 - PHẢI LÀM - CHỌN MÃ QUYỀN LỢI CON CHI TIẾT NHẤT ]
- Sau khi xác định được nhóm quyền lợi cha ở trên, BẠN BẮT BUỘC kiểm tra kỹ "Mô tả chi phí (description)" từng claim để chọn được chính xác quyền lợi chi tiết (mã con) trong nhóm cha đã chọn.
- Một số quyền lợi đặc biệt lưu ý:
    + Chi phí trước nhập viện: Chi phí khám xét nghiệm tối đa 15 ngày trước nhập viện.
    + Chi phí sau xuất viện: Chi phí thuốc, điều trị trong 30 ngày sau xuất viện. Chú ý thông tin mua sắm:
        - Mua tại nhà thuốc Long Châu
        - Mua nhà thuốc khác
    + Dưỡng nhi: Chi phí chăm sóc bé phát sinh khi mẹ chưa xuất viện.
- Nếu không tìm được mã con cụ thể, bạn ĐƯỢC PHÉP sử dụng mã quyền lợi cha ở bước 1.

TÓM LẠI:
→ Luôn luôn tìm và chọn được mã dài nhất, cụ thể nhất.  
→ Bước 2 là bắt buộc nhưng CHỈ là trung gian để đi đến bước 3.  
→ Nếu bước 2 không thể thực hiện chi tiết được thì mới quay lại chọn mã cha ở bước 1.
→ Phải tuyệt đối dựa vào 'benefits_text' ở lần chat hiện tại để phân bổ, tuyệt đối không dựa vào thông tin lịch sử, chỉ dựa vào lần chat hiện tại.
→ Nếu quá khó xác định, chọn 'Unknown'.

THÔNG TIN MỘT SỐ INPUT ĐẦU VÀO claim_info: 
- ICD chính: primary_diagnosis_code
- ICD phụ: secondary_diagnosis_codes
- Lý do nhập viện: admission_reason
- Thông tin lịch sử khám chữa bệnh: medical_history
- Nơi điều trị: clinic_name
- Nơi mua thuốc/vật tư y tế/thực phẩm chức năng: retail_pharmacy
- Khoa khám bệnh: outpatient_department


TRẢ LỜI BẰNG ĐỊNH DẠNG JSON:
[
    {
        "claim_id": "đúng claim ID từ input",
        "benefit_id": "mã quyền lợi chi tiết nhất chọn từ 'benefits_text', ví dụ: 2.1.2.1.9 hoặc Unknown",
        "confidence": 0.95
    },
    ...
]

VÍ DỤ ĐỊNH DẠNG JSON ĐÚNG:
[
    {
        "claim_id": "CLAIM001",
        "benefit_id": "2.1.2.1.1",
        "confidence": 0.98
    }
]

TUYỆT ĐỐI KHÔNG trả lời thêm gì ngoài JSON như trên.
"""

def create_detailed_prompt_ngoaitru():
    """Prompt tối ưu để phân loại chính xác quyền lợi Thai sản."""
    return """Bạn là chuyên viên phân loại quyền lợi Ngoại trú.
Nhiệm vụ duy nhất của bạn là chọn benefit_id CHI TIẾT NHẤT (mã dài nhất có thể) phù hợp với mỗi chi phí được liệt kê.
Tuy nhiên, để làm chính xác điều này, bạn phải làm theo đúng trình tự logic như sau:
[ BƯỚC 1 - KIỂM TRA NỘI TRONG 'benefits_text' ]
    Trường hợp 1: Thông tin 'benefits_text' bị rỗng:
        LUÔN LUÔN gán "benefit_id": "Unknown" cho tất cả claims.
    Trường hợp 2: Có ID quyền lợi (benefit_id) nhưng thiếu đầy đủ chú thích rõ ràng giải thích quyền lợi:
        Xem như mã này KHÔNG hợp lệ. Không được chọn mã này và chọn quyền lợi khác thay thế hoặc ghi Unknown nếu không tìm được mã hợp lệ khác.
    Trường hợp 3: Description mô tả claim khó hiểu, thiếu thông tin hoặc sai chính tả nghiêm trọng:
    Không cố đoán suy diễn. Hãy chọn nhóm cha (bước 2 nếu rõ ràng) hoặc Unknown (ưu tiên Unknown nếu vẫn không chắc).
[ BƯỚC 2 - CHỌN NHÓM QUYỀN LỢI CHA - là bước TRUNG GIAN bắt buộc ]
Dựa vào thông tin dưới đây để chọn quyền lợi cha chính xác nhất cho từng chi phí. Đây là các nhóm chính, ưu tiên kiểm tra theo thứ tự này:
    Quyền lợi răng (2.2.2): Nếu "Mô tả chi phí (description)" hoặc "outpatient_department" (khoa khám bệnh) liên quan đến răng, nha khoa (ví dụ: khám răng, trám răng, nhổ răng, cạo vôi răng).
    Vật lý trị liệu (2.2.3): Nếu "Mô tả chi phí (description)" liên quan đến vật lý trị liệu, phục hồi chức năng.
    Điều trị đông y (2.2.4): Nếu "Mô tả chi phí (description)" liên quan đến khám và điều trị bằng y học cổ truyền, đông y (ví dụ: châm cứu, thuốc bắc, thuốc nam).
    Khám thai định kỳ (ngoại trú) (2.2.5): Nếu "Mô tả chi phí (description)" là khám thai, siêu âm thai, theo dõi thai định kỳ và không liên quan đến sinh đẻ hoặc biến chứng thai sản nội trú.
    Chi phí khám nếu mua thuốc tại hệ thống chuỗi nhà thuốc Long Châu (2.2.6): Nếu 'retail_pharmacy' (Nơi mua thuốc/vật tư y tế) là "Long Châu" VÀ có chi phí khám/đơn thuốc.
    Khám tại phòng khám của FPT (2.2.7): Nếu 'clinic_name' (Nơi điều trị) là phòng khám thuộc FPT (cần danh mục phòng khám FPT nếu có).
    Điều khoản bảo hiểm cho bệnh nghề nghiệp (2.2.8): Nếu "primary_diagnosis_code" (ICD chính), "secondary_diagnosis_codes" (ICD phụ) hoặc "description" chỉ ra là bệnh nghề nghiệp theo quy định.
    Điều khoản bảo hiểm chi phí Lọc thẩm tách (2.2.9): Nếu "description" hoặc "medical_history" (lịch sử khám chữa bệnh) đề cập đến lọc máu, chạy thận, thẩm tách phúc mạc.
    Điều khoản bảo hiểm chi phí HIV/AIDS (2.2.10): Nếu "description" hoặc "medical_history" đề cập đến điều trị HIV/AIDS.
    Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa nói chung (2.2.1): Nếu không thuộc các nhóm trên, đây là quyền lợi ngoại trú tổng quát cho các chi phí khám bệnh, xét nghiệm, chẩn đoán và thuốc theo toa không thuộc các trường hợp đặc biệt khác.
[ BƯỚC 3 - PHẢI LÀM - CHỌN MÃ QUYỀN LỢI CON CHI TIẾT NHẤT ]
    Sau khi xác định được nhóm quyền lợi cha ở trên, BẠN BẮT BUỘC kiểm tra kỹ "Mô tả chi phí (description)" từng claim để chọn được chính xác quyền lợi chi tiết (mã con) trong nhóm cha đã chọn.
    Một số quyền lợi đặc biệt lưu ý để chọn mã con chính xác:
        Trong nhóm 2.2.1 (Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa nói chung):
            Vật tư y tế mua tại nhà thuốc Long Châu (2.2.1.7): Nếu 'description' là vật tư y tế (nước muối, băng gạc...) VÀ 'retail_pharmacy' là "Long Châu".
            Vật tư y tế mua tại nơi khác (2.2.1.1): Nếu 'description' là vật tư y tế VÀ 'retail_pharmacy' KHÔNG PHẢI là Long Châu, hoặc không có thông tin 'retail_pharmacy'.
            Phòng khám tư có dấu, không hóa đơn tài chính (2.2.1.2): Nếu 'clinic_name' là phòng khám tư VÀ chứng từ có dấu nhưng không phải hóa đơn tài chính (phiếu thu, biên lai...).
            Có chẩn đoán bệnh nhưng chưa cần điều trị (2.2.1.3): Nếu có "primary_diagnosis_code" nhưng không có đơn thuốc hoặc không có "next_treatment_plan" (hướng điều trị tiếp theo).
            Phòng khám tư không hóa đơn tài chính & không dấu (2.2.1.4): Nếu 'clinic_name' là phòng khám tư VÀ chứng từ không có dấu và không phải hóa đơn tài chính.
            Rửa mũi xoang tại bệnh viện (2.2.1.5): Nếu 'description' là dịch vụ rửa mũi, xông mũi, hút mũi tại cơ sở y tế.
            Có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể (2.2.1.6): Nếu 'description' mô tả triệu chứng nhưng không có "primary_diagnosis_code" rõ ràng hoặc mã ICD không đặc hiệu (ví dụ Z03) và không có đơn thuốc.
        Trong nhóm 2.2.2 (Quyền lợi răng):
            Điều trị viêm lợi bằng việc lấy cao răng (2.2.2.1): Nếu 'description' là lấy cao răng, cạo vôi răng VÀ chẩn đoán liên quan đến viêm lợi, viêm nướu.
        Trong nhóm 2.2.6 (Chi phí khám nếu mua thuốc tại Long Châu):
            Vật tư y tế (mua tại nơi khác Long Châu) (2.2.6.1): Nếu thuốc mua tại Long Châu, nhưng vật tư y tế trong cùng đợt điều trị lại mua ở nơi khác (hoặc hóa đơn VTYT riêng không ghi Long Châu).
            Vật tư y tế (mua tại Long Châu) (2.2.6.2): Nếu cả thuốc và vật tư y tế đều mua tại Long Châu.
            Rửa mũi xoang tại bệnh viện (khi thuốc mua tại Long Châu) (2.2.6.3): Nếu 'description' là dịch vụ rửa mũi, xông mũi VÀ thuốc cho đợt điều trị đó được mua tại Long Châu.
    Nếu không tìm được mã con cụ thể, bạn ĐƯỢC PHÉP sử dụng mã quyền lợi cha đã xác định ở Bước 2.
TÓM LẠI:
→ Luôn luôn tìm và chọn được mã dài nhất, cụ thể nhất.
→ Bước 2 là bắt buộc nhưng CHỈ là trung gian để đi đến bước 3.
→ Nếu bước 3 không thể xác định mã con chi tiết, mới sử dụng mã cha từ Bước 2.
→ Phải tuyệt đối dựa vào 'benefits_text' ở lần chat hiện tại để phân bổ, tuyệt đối không dựa vào thông tin lịch sử, chỉ dựa vào lần chat hiện tại.
→ Nếu quá khó xác định, chọn 'Unknown'.

THÔNG TIN MỘT SỐ INPUT ĐẦU VÀO claim_info (CÓ THỂ THAY ĐỔI TÙY VÀO TỪNG HỒ SƠ): 
- ICD chính: primary_diagnosis_code
- ICD phụ: secondary_diagnosis_codes
- Lý do nhập viện: admission_reason
- Thông tin lịch sử khám chữa bệnh: medical_history
- Nơi điều trị: clinic_name
- Nơi mua thuốc/vật tư y tế/thực phẩm chức năng: retail_pharmacy
- Khoa khám bệnh: outpatient_department
- Hướng điều trị tiếp theo: next_treatment_plan
- Loại chứng từ: document_type

TRẢ LỜI BẰNG ĐỊNH DẠNG JSON:
[
    {
        "claim_id": "đúng claim ID từ input",
        "benefit_id": "mã quyền lợi chi tiết nhất chọn từ 'benefits_text', ví dụ: 2.1.2.1.9 hoặc Unknown",
        "confidence": 0.95
    },
    ...
]

VÍ DỤ ĐỊNH DẠNG JSON ĐÚNG:
[
    {
        "claim_id": "CLAIM001",
        "benefit_id": "2.1.2.1.1",
        "confidence": 0.98
    }
]

TUYỆT ĐỐI KHÔNG trả lời thêm gì ngoài JSON như trên.
"""

class MultiClaimClassifier:
    def __init__(self, azure_api_key: str, gemini_api_key: str):
        # Initialize Azure OpenAI client
        self.openai_client = AzureOpenAI(
            api_version="2024-12-01-preview",
            azure_endpoint="https://admin-m9kv2jak-eastus2.cognitiveservices.azure.com/",
            api_key=azure_api_key
        )
        # Initialize Gemini client
        genai.configure(api_key=gemini_api_key)
        self.gemini_model = genai.GenerativeModel('gemini-pro')

    async def classify_with_openai_ngoaitru(self, claim_info: Dict[str, Any], claims: List[dict], benefits_text: str) -> List[dict]:
        try:
            claims_text  = {"claim_info": claim_info, "claims": claims, "benefits_text": benefits_text}
            claims_text = str(claims_text)
            print("claims_text:", claims_text)
            prompt = create_detailed_prompt_ngoaitru()
            print("prompt: ", prompt)

            user1 = """{
                        "claim_info": {
                            "primary_diagnosis_code": "H04.5",
                            "secondary_diagnosis_codes": [],
                            "admission_reason": "",
                            "medical_history": "Không rõ",
                            "clinic_name": "",
                            "retail_pharmacy": "",
                            "outpatient_department": "Không rõ", // Assuming general outpatient if not specified
                            "next_treatment_plan": "",
                            "document_type": ""
                        },
                        "claims": [
                            {"amount": 72000.0, "claim_id": "dd856403-4269-491c-8feb-685b1771fc81", "description": "Liposic Eye gel 2% 20g", "service": "Liposic Eye gel 2% 20g"},
                            {"amount": 800000.0, "claim_id": "907efc2c-0a2c-405c-8b19-2cdb579b7292", "description": "Bơm lệ đạo người lớn - 1 mắt", "service": "Bơm lệ đạo người lớn - 1 mắt"},
                            {"amount": 300000.0, "claim_id": "7aaf19cb-605a-4ddf-8459-d71523fcfe0d", "description": "Khám mắt", "service": "Khám mắt"},
                            {"amount": 81000.0, "claim_id": "012ca328-880d-4fe7-bc6f-0d8a21bbac07", "description": "Relestat 5ml 0.5mg/ml", "service": "Relestat 5ml 0.5mg/ml"},
                            {"amount": 88000.0, "claim_id": "1f7c1f41-f63d-494f-89d3-fa37a3d9ff06", "description": "Alegysal1mg/ml, lọ 5ml", "service": "Alegysal1mg/ml, lọ 5ml"},
                            {"amount": 137000.0, "claim_id": "1faac776-73c1-4c6f-a29a-6d08dd46200d", "description": "Diquas 30mg/ml, lọ 5ml", "service": "Diquas 30mg/ml, lọ 5ml"},
                            {"amount": 132300.0, "claim_id": "dc692888-8207-490e-98c4-3c82e1509139", "description": "Sanlein Eye Drop 0.3% 5ml/1 lọ", "service": "Sanlein Eye Drop 0.3% 5ml/1 lọ"},
                            {"amount": 300000.0, "claim_id": "36b1405f-9ad0-40dd-8bbf-43214850b09f", "description": "Khám Mặt | PTM - Phòng khám mặt 11-36", "service": "Khám Mặt | PTM - Phòng khám mặt 11-36"},
                            {"amount": 137000.0, "claim_id": "4bb903d3-7bfe-49ae-abb1-8de6bf882528", "description": "DIQUAS 3% 5ml", "service": "DIQUAS 3% 5ml"},
                            {"amount": 72000.0, "claim_id": "2a76a556-39b7-43e0-8e66-87a9a7300faa", "description": "Liposic Eye gel 2% 10g", "service": "Liposic Eye gel 2% 10g"},
                            {"amount": 132300.0, "claim_id": "a1efcecc-ddd2-4988-be0e-60451a4377f7", "description": "Sanlein 0.3% 5ml", "service": "Sanlein 0.3% 5ml"},
                            {"amount": 88000.0, "claim_id": "19600872-bfbf-40e0-a02d-999ca27b35cd", "description": "Alegysal 0.1% 5ml", "service": "Alegysal 0.1% 5ml"}
                        ],
                        "benefits_text": "2.2.1 Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa\n2.2.1.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.2.1.2 Phòng khám tư có dấu nhưng không có hóa đơn tài chính (hoạt động hợp pháp)\n2.2.1.3 Có chẩn đoán bệnh nhưng chưa cần điều trị (chưa có đơn thuốc hoặc chưa thực hiện điều trị theo chỉ định)\n2.2.1.4 Phòng khám tư không có hóa đơn tài chính & không dấu (Điều khoản này áp dụng cho phòng khám bác sỹ tư có giấy phép hành nghề nhưng không có đăng ký kinh doanh)\n2.2.1.5 Rửa mũi xoang tại bệnh viện\n2.2.1.6 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể\n2.2.1.7 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.2.2 Quyền lợi răng\n2.2.2.1 Điều trị viêm lợi bằng việc lấy cao răng\n2.2.3 Vật lý trị liệu\n2.2.5 Khám thai định kỳ\n2.2.6 Chi phí/lần khám nếu hồ sơ bồi thường có mua thuốc tại hệ thống chuỗi nhà thuốc FPT Long Châu\n2.2.6.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.2.6.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.2.6.3 Rửa mũi xoang tại bệnh viện\n2.2.6.4 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể"
                    }"""
            assistant1 = """[
                        {"claim_id": "dd856403-4269-491c-8feb-685b1771fc81", "benefit_id": "2.2.1", "confidence": 0.90},
                        {"claim_id": "907efc2c-0a2c-405c-8b19-2cdb579b7292", "benefit_id": "2.2.1", "confidence": 0.85},
                        {"claim_id": "7aaf19cb-605a-4ddf-8459-d71523fcfe0d", "benefit_id": "2.2.1", "confidence": 0.87},
                        {"claim_id": "012ca328-880d-4fe7-bc6f-0d8a21bbac07", "benefit_id": "2.2.1", "confidence": 0.98},
                        {"claim_id": "1f7c1f41-f63d-494f-89d3-fa37a3d9ff06", "benefit_id": "2.2.1", "confidence": 0.99},
                        {"claim_id": "1faac776-73c1-4c6f-a29a-6d08dd46200d", "benefit_id": "2.2.1", "confidence": 0.93},
                        {"claim_id": "dc692888-8207-490e-98c4-3c82e1509139", "benefit_id": "2.2.1", "confidence": 0.92},
                        {"claim_id": "36b1405f-9ad0-40dd-8bbf-43214850b09f", "benefit_id": "2.2.1", "confidence": 0.95},
                        {"claim_id": "4bb903d3-7bfe-49ae-abb1-8de6bf882528", "benefit_id": "2.2.1", "confidence": 0.98},
                        {"claim_id": "2a76a556-39b7-43e0-8e66-87a9a7300faa", "benefit_id": "2.2.1", "confidence": 0.95},
                        {"claim_id": "a1efcecc-ddd2-4988-be0e-60451a4377f7", "benefit_id": "2.2.1", "confidence": 0.95},
                        {"claim_id": "19600872-bfbf-40e0-a02d-999ca27b35cd", "benefit_id": "2.2.1", "confidence": 0.97}
                    ]"""
            user2 = """{
                    "claim_info": {
                        "primary_diagnosis_code": "J32.9",
                        "secondary_diagnosis_codes": ["K05.1", "M79.1"],
                        "admission_reason": "",
                        "medical_history": "Tiền sử viêm xoang mạn tính, đau mỏi cơ.",
                        "clinic_name": "Phòng khám Đa khoa Quốc tế ABC",
                        "retail_pharmacy": "",
                        "outpatient_department": "Tổng hợp",
                        "next_treatment_plan": "",
                        "document_type": "Hóa đơn GTGT"
                    },
                    "claims": [
                        {
                            "amount": 350000.0,
                            "claim_id": "c1a1b1c1-0001-4000-8000-abc123def456",
                            "description": "Khám chuyên khoa Tai Mũi Họng và đơn thuốc điều trị viêm xoang",
                            "service": "Khám TMH + Đơn thuốc Xyzal"
                        },
                        {
                            "amount": 85000.0,
                            "claim_id": "c1a1b1c1-0002-4000-8000-abc123def457",
                            "description": "Nước muối biển Sterimar và Bông y tế Bạch Tuyết mua tại Nhà thuốc An Khang",
                            "service": "Vật tư y tế: Sterimar, Bông"
                        },
                        {
                            "amount": 150000.0,
                            "claim_id": "c1a1b1c1-0003-4000-8000-abc123def458",
                            "description": "Thực hiện thủ thuật rửa mũi xoang tại phòng khám",
                            "service": "Rửa mũi xoang"
                        },
                        {
                            "amount": 450000.0,
                            "claim_id": "c1a1b1c1-0004-4000-8000-abc123def459",
                            "description": "Cạo vôi răng và điều trị viêm lợi nhẹ tại khoa Răng Hàm Mặt",
                            "service": "Lấy cao răng - Điều trị viêm lợi"
                        },
                        {
                            "amount": 300000.0,
                            "claim_id": "c1a1b1c1-0005-4000-8000-abc123def450",
                            "description": "Phiếu thu dịch vụ Vật lý trị liệu giảm đau cơ vai gáy",
                            "service": "Vật lý trị liệu vai gáy"
                        }
                    ],
                    "benefits_text": "2.2.1 Chi phí khám, xét nghiệm, chẩn đoán, thuốc kê toa\n2.2.1.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.2.1.2 Phòng khám tư có dấu nhưng không có hóa đơn tài chính (hoạt động hợp pháp)\n2.2.1.3 Có chẩn đoán bệnh nhưng chưa cần điều trị (chưa có đơn thuốc hoặc chưa thực hiện điều trị theo chỉ định)\n2.2.1.4 Phòng khám tư không có hóa đơn tài chính & không dấu (Điều khoản này áp dụng cho phòng khám bác sỹ tư có giấy phép hành nghề nhưng không có đăng ký kinh doanh)\n2.2.1.5 Rửa mũi xoang tại bệnh viện\n2.2.1.6 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể\n2.2.1.7 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.2.2 Quyền lợi răng\n2.2.2.1 Điều trị viêm lợi bằng việc lấy cao răng\n2.2.3 Vật lý trị liệu\n2.2.5 Khám thai định kỳ\n2.2.6 Chi phí/lần khám nếu hồ sơ bồi thường có mua thuốc tại hệ thống chuỗi nhà thuốc FPT Long Châu\n2.2.6.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.2.6.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.2.6.3 Rửa mũi xoang tại bệnh viện\n2.2.6.4 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể"
                }"""

            assistant2 = """[
                    {
                        "claim_id": "c1a1b1c1-0001-4000-8000-abc123def456",
                        "benefit_id": "2.2.1",
                        "confidence": 0.92
                    },
                    {
                        "claim_id": "c1a1b1c1-0002-4000-8000-abc123def457",
                        "benefit_id": "2.2.1.1",
                        "confidence": 0.95
                    },
                    {
                        "claim_id": "c1a1b1c1-0003-4000-8000-abc123def458",
                        "benefit_id": "2.2.1.5",
                        "confidence": 0.99
                    },
                    {
                        "claim_id": "c1a1b1c1-0004-4000-8000-abc123def459",
                        "benefit_id": "2.2.2.1",
                        "confidence": 0.95
                    },
                    {
                        "claim_id": "c1a1b1c1-0005-4000-8000-abc123def450",
                        "benefit_id": "2.2.3",
                        "confidence": 0.95
                    }
                ]"""
            
            messages=[
                    {"role": "system", "content": str(prompt)},
                    {"role": "user", "content": str(user1)},
                    {"role": "assistant", "content": str(assistant1)},
                    {"role": "user", "content": str(user2)},
                    {"role": "assistant", "content": str(assistant2)},
                    {"role": "user", "content": str(claims_text)}
                ]
            print("messages: ", messages)
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-4o",  # Ensure this model is available in your Azure deployment
                messages=messages,
                temperature=0
            )

            response_text = response.choices[0].message.content.strip()
            print("Azure response_text raw: ", response_text)
            response_text = re.sub(r'^```json\s*|\s*```$', '', response_text)
            print("Azure response_text: ", response_text)
            return json.loads(response_text)
        except Exception as e:
            print(f"Azure OpenAI API error details: {str(e)}")
            return []

    async def classify_with_openai_thaisan(self, claim_info: Dict[str, Any], claims: List[dict], benefits_text: str) -> List[dict]:
        try:
            claims_text  = {"claim_info": claim_info, "claims": claims, "benefits_text": benefits_text}
            claims_text = str(claims_text)
            print("claims_text:", claims_text)
            prompt = create_detailed_prompt_thaisan()
            print("prompt: ", prompt)

            user1 = """{
                        "claim_info": {
                            "primary_diagnosis_code": "Z34.8",
                            "secondary_diagnosis_codes": [],
                            "admission_reason": "Thai 36 tuần 6 ngày đang phát triển",
                            "medical_history": "Không rõ",
                            "clinic_name": "Bệnh viện đa khoa Hồng Ngọc - Phúc Trường Minh",
                            "retail_pharmacy": "Không rõ",
                            "outpatient_department": "Phòng Siêu Âm"
                        },
                        "claims": [
                            {"amount": 35000, "claim_id": "26446822093d8ceb77c33c86b7b0683c", "description": "SA một thai - tuổi thai 3 tháng trở lên", "service": ""},
                            {"amount": 35000, "claim_id": "57dff4a27e742e10d23e236ea1f4b9f7", "description": "SA một thai - tuổi thai 3 tháng trở lên", "service": ""}
                        ],
                        "benefits_text": "2.2.1 Điều trị ngoại trú chung\\n2.2.1.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\\n2.2.1.2 Phòng khám tư có dấu nhưng không có hóa đơn tài chính (hoạt động hợp pháp)\\n2.2.1.3 Khám ngoại trú không hướng điều trị\\n2.2.1.4 Phòng khám tư không có hóa đơn tài chính & không dấu (Điều khoản này áp dụng cho phòng khám bác sỹ tư có giấy phép hành nghề nhưng không có đăng ký kinh doanh)\\n2.2.1.5 Rửa mũi xoang tại bệnh viện\\n2.2.1.6 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể\\n2.2.2 Quyền lợi răng\\n2.2.2.1 Điều trị viêm lợi bằng việc lấy cao răng\\n2.2.3 Vật lý trị liệu\\n2.2.5 Khám thai định kỳ\\n2.2.6 Chi phí/lần khám nếu hồ sơ bồi thường có mua thuốc tại hệ thống chuỗi nhà thuốc FPT Long Châu"
                    }"""
            assistant1 = """[
                        {"claim_id": "26446822093d8ceb77c33c86b7b0683c", "benefit_id": "2.1.2.6", "confidence": 0.95},
                        {"claim_id": "57dff4a27e742e10d23e236ea1f4b9f7", "benefit_id": "2.1.2.6", "confidence": 0.95}
                        ]"""
            user2 = """{
                        "claim_info": {
                            "primary_diagnosis_code": "O24.4",
                            "secondary_diagnosis_codes": ["Z35.9"],
                            "admission_reason": "Đái tháo đường thai kỳ/ Thai 26 tuần",
                            "medical_history": "Không rõ",
                            "clinic_name": "Bệnh viện Nội tiết tỉnh Bắc Giang",
                            "retail_pharmacy": "Không rõ",
                            "outpatient_department": ""
                        },
                        "claims": [
                            {"amount": 700, "claim_id": "claim_XYZ01", "description": "Khám Nội tiết", "service": ""},
                            {"amount": 34300, "claim_id": "claim_XYZ02", "description": "Giường Nội khoa loại 1", "service": ""}
                        ],
                        "benefits_text": "2.2.1 Điều trị ngoại trú chung\\n2.2.1.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\\n2.2.1.2 Phòng khám tư có dấu nhưng không có hóa đơn tài chính (hoạt động hợp pháp)\\n2.2.1.3 Khám ngoại trú không hướng điều trị\\n2.2.1.4 Phòng khám tư không có hóa đơn tài chính & không dấu (Điều khoản này áp dụng cho phòng khám bác sỹ tư có giấy phép hành nghề nhưng không có đăng ký kinh doanh)\\n2.2.1.5 Rửa mũi xoang tại bệnh viện\\n2.2.1.6 Trường hợp có triệu chứng, đi khám nhưng không có kết luận bệnh cụ thể\\n2.2.2 Quyền lợi răng\\n2.2.2.1 Điều trị viêm lợi bằng việc lấy cao răng\\n2.2.3 Vật lý trị liệu\\n2.2.5 Khám thai định kỳ\\n2.2.6 Chi phí/lần khám nếu hồ sơ bồi thường có mua thuốc tại hệ thống chuỗi nhà thuốc FPT Long Châu"
                    }"""

            assistant2 = """[
                        {"claim_id": "claim_XYZ01", "benefit_id": "2.1.2.3.11", "confidence": 0.9},
                        {"claim_id": "claim_XYZ02", "benefit_id": "2.1.2.3.1", "confidence": 1.0}
                        ]"""
            user3 = """{
                        "claim_info": {
                            "primary_diagnosis_code": "O82.1",
                            "secondary_diagnosis_codes": ["O32.1", "Z39.0", "O86.0"],
                            "admission_reason": "Nhập viện sinh mổ chủ động do thai ngôi ngược, 39 tuần",
                            "medical_history": "Con lần 1, thai 39 tuần ngôi ngược. Chỉ định mổ lấy thai. Sau sinh có dấu hiệu nhiễm trùng nhẹ vết mổ.",
                            "clinic_name": "Bệnh viện Phụ sản Hạnh Phúc",
                            "retail_pharmacy": "Nhà thuốc FPT Long Châu và Nhà thuốc An Khang",
                            "outpatient_department": "Chưa có thông tin"
                        },
                        "claims": [
                            {"amount": 2500000, "claim_id": "CSM001", "description": "Tiền phòng đơn ngày 1", "service": ""},
                            {"amount": 2500000, "claim_id": "CSM002", "description": "Tiền phòng đơn ngày 2", "service": ""},
                            {"amount": 2500000, "claim_id": "CSM003", "description": "Tiền phòng đơn ngày 3", "service": ""},
                            {"amount": 15000000, "claim_id": "CSM004", "description": "Phí phẫu thuật sinh mổ (gói)", "service": ""},
                            {"amount": 850000, "claim_id": "CSM005", "description": "Xét nghiệm đông máu cơ bản trước mổ", "service": "Bệnh viện Phụ sản Hạnh Phúc"},
                            {"amount": 1200000, "claim_id": "CSM006", "description": "Thuốc giảm đau Paracetamol, kháng sinh dự phòng Cefuroxim trong viện", "service": "Bệnh viện Phụ sản Hạnh Phúc"},
                            {"amount": 350000, "claim_id": "CSM007", "description": "Vật tư y tế tiêu hao: Bông, gạc, dung dịch sát khuẩn Povidine", "service": "Bệnh viện Phụ sản Hạnh Phúc"},
                            {"amount": 450000, "claim_id": "CSM008", "description": "Siêu âm ổ bụng kiểm tra sau mổ", "service": ""},
                            {"amount": 500000, "claim_id": "CSM009", "description": "Khám chuyên khoa đánh giá vết mổ (ngày 3)", "service": "Bệnh viện Phụ sản Hạnh Phúc"},
                            {"amount": 750000, "claim_id": "CSM010", "description": "Thuốc kháng sinh Augmentin điều trị nhiễm trùng vết mổ", "service": "Bệnh viện Phụ sản Hạnh Phúc"},
                            {"amount": 300000, "claim_id": "CSM011", "description": "Phí tắm bé và vệ sinh rốn ngày 1", "service": ""},
                            {"amount": 1100000, "claim_id": "CSM012", "description": "Xét nghiệm sàng lọc sơ sinh (G6PD, TSH)", "service": "Bệnh viện Phụ sản Hạnh Phúc"},
                            {"amount": 450000, "claim_id": "CSM013", "description": "Thuốc kháng sinh Zinnat 500mg (tiếp tục đơn)", "service": "Nhà thuốc Long Châu"},
                            {"amount": 150000, "claim_id": "CSM014", "description": "Thuốc giảm đau Efferalgan Codein", "service": "Nhà thuốc Long Châu"},
                            {"amount": 95000, "claim_id": "CSM015", "description": "Nước muối sinh lý Natri Clorid 0.9%, gạc vô trùng Urgo", "service": "Nhà thuốc Long Châu"},
                            {"amount": 280000, "claim_id": "CSM016", "description": "Tái khám vết mổ tại phòng khám tư", "service": "Phòng khám Sản phụ khoa BS Mai"},
                            {"amount": 120000, "claim_id": "CSM017", "description": "Vitamin tổng hợp Elevit sau sinh Nhà thuốc An Khang", "service": "Nhà thuốc An Khang"}
                        ],
                        "benefits_text": "2.1 Điều trị nội trú\n2.1.2 Thai sản\n2.1.2.1 Sinh thường\n2.1.2.1.1 Tiền giường\n2.1.2.1.10 Chi phí xe cấp cứu\n2.1.2.1.11 Bác sĩ tư vấn\n2.1.2.1.12 Hộ lý chăm sóc\n2.1.2.1.13 Người trông coi\n2.1.2.1.2 Tiền trên ngày điều trị\n2.1.2.1.3 Số ngày điều trị\n2.1.2.1.4 Chi phí thuốc - vật tư tiêu hao bệnh viện\n2.1.2.1.5 Trợ cấp nằm viện\n2.1.2.1.6 Trợ cấp nằm viện tại bệnh viện công lập, trừ khoa quốc tế, khoa dịch vụ, tự nguyện\n2.1.2.1.7 Trợ cấp nằm viện tại bệnh viện ngoài công lập hoặc khoa quốc tế, dịch vụ, tự nguyện bệnh viện công lập\n2.1.2.1.8 Chi phí trước nhập viện\n2.1.2.1.9 Chi phí sau xuất viện\n2.1.2.1.9.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.1.2.1.9.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.1.2.2 Sinh mổ\n2.1.2.2.1 Tiền giường\n2.1.2.2.10 Chi phí xe cấp cứu\n2.1.2.2.11 Bác sĩ tư vấn\n2.1.2.2.12 Hộ lý chăm sóc\n2.1.2.2.13 Người trông coi\n2.1.2.2.14 Chi phí phẫu thuật\n2.1.2.2.2 Tiền trên ngày điều trị\n2.1.2.2.3 Số ngày điều trị\n2.1.2.2.4 Chi phí thuốc - vật tư tiêu hao bệnh viện\n2.1.2.2.5 Trợ cấp nằm viện\n2.1.2.2.6 Trợ cấp nằm viện tại bệnh viện công lập, trừ khoa quốc tế, khoa dịch vụ, tự nguyện\n2.1.2.2.7 Trợ cấp nằm viện tại bệnh viện ngoài công lập hoặc khoa quốc tế, dịch vụ, tự nguyện bệnh viện công lập\n2.1.2.2.8 Chi phí trước nhập viện\n2.1.2.2.9 Chi phí sau xuất viện\n2.1.2.2.9.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.1.2.2.9.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.1.2.3 Biến chứng thai sản\n2.1.2.3.1 Tiền giường\n2.1.2.3.10 Chi phí xe cấp cứu\n2.1.2.3.11 Bác sĩ tư vấn\n2.1.2.3.12 Hộ lý chăm sóc\n2.1.2.3.13 Người trông coi\n2.1.2.3.14 Chi phí phẫu thuật\n2.1.2.3.2 Tiền trên ngày điều trị\n2.1.2.3.3 Số ngày điều trị\n2.1.2.3.4 Chi phí thuốc - vật tư tiêu hao bệnh viện\n2.1.2.3.5 Trợ cấp nằm viện\n2.1.2.3.6 Trợ cấp nằm viện tại bệnh viện công lập, trừ khoa quốc tế, khoa dịch vụ, tự nguyện\n2.1.2.3.7 Trợ cấp nằm viện tại bệnh viện ngoài công lập hoặc khoa quốc tế, dịch vụ, tự nguyện bệnh viện công lập\n2.1.2.3.8 Chi phí trước nhập viện\n2.1.2.3.9 Chi phí sau xuất viện\n2.1.2.3.9.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.1.2.3.9.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.1.2.4 Sinh mổ không theo chỉ định của bác sĩ\n2.1.2.4.1 Tiền giường\n2.1.2.4.10 Chi phí xe cấp cứu\n2.1.2.4.11 Bác sĩ tư vấn\n2.1.2.4.12 Hộ lý chăm sóc\n2.1.2.4.13 Người trông coi\n2.1.2.4.2 Tiền trên ngày điều trị\n2.1.2.4.3 Số ngày điều trị\n2.1.2.4.4 Chi phí thuốc - vật tư tiêu hao bệnh viện\n2.1.2.4.5 Trợ cấp nằm viện\n2.1.2.4.6 Trợ cấp nằm viện tại bệnh viện công lập, trừ khoa quốc tế, khoa dịch vụ, tự nguyện\n2.1.2.4.7 Trợ cấp nằm viện tại bệnh viện ngoài công lập hoặc khoa quốc tế, dịch vụ, tự nguyện bệnh viện công lập\n2.1.2.4.8 Chi phí trước nhập viện\n2.1.2.4.9 Chi phí sau xuất viện\n2.1.2.4.9.1 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…) tại nhà thuốc Long Châu\n2.1.2.4.9.2 Vật tư y tế (nước muối sinh lý, nước muối biển, nước sát trùng, nước rửa vệ sinh…)\n2.1.2.5 Dưỡng nhi\n2.1.2.6 Khám thai định kỳ"
                    }"""
            assistant3 = """[
                        {"claim_id": "CSM001", "benefit_id": "2.1.2.2.1", "confidence": 1.0},
                        {"claim_id": "CSM002", "benefit_id": "2.1.2.2.1", "confidence": 1.0},
                        {"claim_id": "CSM003", "benefit_id": "2.1.2.2.1", "confidence": 1.0},
                        {"claim_id": "CSM004", "benefit_id": "2.1.2.2.14", "confidence": 1.0},
                        {"claim_id": "CSM005", "benefit_id": "2.1.2.2.4", "confidence": 0.9},
                        {"claim_id": "CSM006", "benefit_id": "2.1.2.2.4", "confidence": 1.0},
                        {"claim_id": "CSM007", "benefit_id": "2.1.2.2.4", "confidence": 1.0},
                        {"claim_id": "CSM008", "benefit_id": "2.1.2.2.4", "confidence": 0.9},
                        {"claim_id": "CSM009", "benefit_id": "2.1.2.3.11", "confidence": 0.95},
                        {"claim_id": "CSM010", "benefit_id": "2.1.2.3.4", "confidence": 1.0},
                        {"claim_id": "CSM011", "benefit_id": "2.1.2.5", "confidence": 1.0},
                        {"claim_id": "CSM012", "benefit_id": "2.1.2.5", "confidence": 1.0},
                        {"claim_id": "CSM013", "benefit_id": "2.1.2.3.9.1", "confidence": 0.95},
                        {"claim_id": "CSM014", "benefit_id": "2.1.2.2.9.1", "confidence": 0.9},
                        {"claim_id": "CSM015", "benefit_id": "2.1.2.3.9.1", "confidence": 0.95},
                        {"claim_id": "CSM016", "benefit_id": "2.1.2.3.9", "confidence": 0.9},
                        {"claim_id": "CSM017", "benefit_id": "2.1.2.2.9.2", "confidence": 0.85}
                    ]"""
            user4 = """{
                        "claim_info": {
                            "admission_reason": "Khám thai định kỳ thai 32 tuần",
                            "clinic_name": "Phòng khám Sản phụ khoa ABC",
                            "medical_history": "Mang thai lần 2, thai phát triển bình thường",
                            "outpatient_department": "Phòng siêu âm thai",
                            "primary_diagnosis_code": "Z34.0",
                            "retail_pharmacy": "Không rõ",
                            "secondary_diagnosis_codes": []
                        },
                        "claims": [
                            {"amount": 150000, "claim_id": "KT001", "description": "Khám thai định kỳ tuần thai 32", "service": "Phòng khám Sản phụ khoa ABC"},
                            {"amount": 100000, "claim_id": "KT002", "description": "Siêu âm thai 4D thường quy (thai trên 22 tuần)", "service": "Phòng khám Sản phụ khoa ABC"}
                        ],
                        "benefits_text": "yuyu yyyuyu 2.1.2.1.1 2.1.2.3.9.1 2.1.2.3"
                        }"""
            assistant4 = """[
                        {"claim_id": "KT001", "benefit_id": "Unknown", "confidence": 1.0},
                        {"claim_id": "KT002", "benefit_id": "Unknown", "confidence": 1.0}
                        ]"""
            messages=[
                    {"role": "system", "content": str(prompt)},
                    {"role": "user", "content": str(user1)},
                    {"role": "assistant", "content": str(assistant1)},
                    {"role": "user", "content": str(user2)},
                    {"role": "assistant", "content": str(assistant2)},
                    {"role": "user", "content": str(user3)},
                    {"role": "assistant", "content": str(assistant3)},
                    {"role": "user", "content": str(user4)},
                    {"role": "assistant", "content": str(assistant4)},
                    {"role": "user", "content": str(claims_text)}
                ]
            print("messages: ", messages)
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-4o-mini",  # Ensure this model is available in your Azure deployment
                messages=messages,
                temperature=0
            )

            response_text = response.choices[0].message.content.strip()
            print("Azure response_text raw: ", response_text)
            response_text = re.sub(r'^```json\s*|\s*```$', '', response_text)
            print("Azure response_text: ", response_text)
            return json.loads(response_text)
        except Exception as e:
            print(f"Azure OpenAI API error details: {str(e)}")
            return []

    async def classify_with_openai(self, claims: List[dict], benefits_text: str) -> List[dict]:
        try:
            prompt = create_detailed_prompt(claims, benefits_text)
            messages=[
                    {"role": "system", "content": "You are an insurance claim classifier. Return only the JSON array as specified in the prompt."},
                    {"role": "user", "content": prompt}
                ]
            print("messages: ", messages)
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-4o-mini",  # Ensure this model is available in your Azure deployment
                messages=messages,
                temperature=0
            )

            response_text = response.choices[0].message.content.strip()
            response_text = re.sub(r'^```json\s*|\s*```$', '', response_text)
            print("Azure response_text: ", response_text)
            return json.loads(response_text)
        except Exception as e:
            print(f"Azure OpenAI API error details: {str(e)}")
            return []
        
    async def classify_with_gemini(self, claims: List[dict], benefits_text: str) -> List[dict]:
        try:
            prompt = create_detailed_prompt(claims, benefits_text)
            response = await asyncio.to_thread(
                self.gemini_model.generate_content,
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0
                )
            )

            response_text = response.text.strip()
            response_text = re.sub(r'^```json\s*|\s*```$', '', response_text)
            print("GEMINI response_text: ", response_text)
            return json.loads(response_text)
        except Exception as e:
            print(f"Gemini API error details: {str(e)}")
            return []

    def _group_by_benefit(self, claims: List[dict], classifications: List[dict]) -> List[dict]:
        """Group claims by benefit ID with individual confidence scores"""
        benefit_groups = defaultdict(list)

        # Create mapping of claim_id to original claim data
        claim_map = {claim["claim_id"]: claim for claim in claims}

        # Create mapping of claim_id to confidence from classifications
        confidence_map = {c["claim_id"]: c["confidence"] for c in classifications}

        # Group claims by benefit ID while preserving individual confidence scores
        for classification in classifications:
            claim_id = classification["claim_id"]
            benefit_id = classification["benefit_id"]

            if claim_id in claim_map:
                claim_data = claim_map[claim_id].copy()
                claim_data["confidence"] = confidence_map[claim_id]
                benefit_groups[benefit_id].append(claim_data)

        # Convert to list of benefit classifications
        result = []
        for benefit_id, claims_in_group in benefit_groups.items():
            result.append({
                "benefit_id": benefit_id,
                "claims": claims_in_group,
                "confidence": sum(c["confidence"] for c in claims_in_group) / len(claims_in_group)
            })

        return result 

    async def classify_claims(self, claims: List[dict], benefits_text: str) -> Dict[str, Any]:
        """Classify claims and group by benefits"""
        [openai_results, gemini_results] = await asyncio.gather(
            self.classify_with_openai(claims, benefits_text),
            self.classify_with_gemini(claims, benefits_text)
        )

        # Group results by benefit
        openai_grouped = self._group_by_benefit(claims, openai_results)
        gemini_grouped = self._group_by_benefit(claims, gemini_results)

        # Combine results
        all_benefit_ids = set(
            [b["benefit_id"] for b in openai_grouped] +
            [b["benefit_id"] for b in gemini_grouped]
        )

        combined_results = []
        for benefit_id in all_benefit_ids:
            openai_benefit = next((b for b in openai_grouped if b["benefit_id"] == benefit_id), None)
            gemini_benefit = next((b for b in gemini_grouped if b["benefit_id"] == benefit_id), None)

            result = {
                "benefit_id": benefit_id,
                "openai_classification": {
                    "claims": [
                        {
                            "claim_id": c["claim_id"],
                            "service": c["service"],
                            "description": c["description"],
                            "amount": c["amount"],
                            "confidence": c["confidence"]
                        } for c in (openai_benefit["claims"] if openai_benefit else [])
                    ],
                    "average_confidence": openai_benefit["confidence"] if openai_benefit else 0
                },
                "gemini_classification": {
                    "claims": [
                        {
                            "claim_id": c["claim_id"],
                            "service": c["service"],
                            "description": c["description"],
                            "amount": c["amount"],
                            "confidence": c["confidence"]
                        } for c in (gemini_benefit["claims"] if gemini_benefit else [])
                    ],
                    "average_confidence": gemini_benefit["confidence"] if gemini_benefit else 0
                }
            }

            # Check for consensus
            if openai_benefit and gemini_benefit:
                openai_claim_ids = {c["claim_id"] for c in openai_benefit["claims"]}
                gemini_claim_ids = {c["claim_id"] for c in gemini_benefit["claims"]}
                consensus_claim_ids = openai_claim_ids.intersection(gemini_claim_ids)

                if consensus_claim_ids:
                    # Create a map of claim_id to confidence pairs from both models
                    openai_confidences = {c["claim_id"]: c["confidence"] for c in openai_benefit["claims"]}
                    gemini_confidences = {c["claim_id"]: c["confidence"] for c in gemini_benefit["claims"]}

                    consensus_claims = []
                    for claim_id in consensus_claim_ids:
                        claim_data = next(c for c in claims if c["claim_id"] == claim_id)
                        consensus_claim = {
                            "claim_id": claim_data["claim_id"],
                            "service": claim_data["service"],
                            "description": claim_data["description"],
                            "amount": claim_data["amount"],
                            "confidence": (openai_confidences[claim_id] + gemini_confidences[claim_id]) / 2
                        }
                        consensus_claims.append(consensus_claim)

                    result["consensus"] = {
                        "claims": consensus_claims,
                        "average_confidence": sum(c["confidence"] for c in consensus_claims) / len(consensus_claims)
                    }
                else:
                    result["consensus"] = None
            else:
                result["consensus"] = None

            combined_results.append(result)

        return combined_results
    
    async def classify_claims_ngoaitru(self, claim_info: Dict[str, Any],claims: List[dict], benefits_text: str) -> Dict[str, Any]:
        """Classify claims and group by benefits"""
        [openai_results, gemini_results] = await asyncio.gather(
            self.classify_with_openai_ngoaitru(claim_info, claims, benefits_text),
            self.classify_with_gemini(claims, benefits_text)
        )

        # Group results by benefit
        openai_grouped = self._group_by_benefit(claims, openai_results)
        gemini_grouped = self._group_by_benefit(claims, gemini_results)

        # Combine results
        all_benefit_ids = set(
            [b["benefit_id"] for b in openai_grouped] +
            [b["benefit_id"] for b in gemini_grouped]
        )

        combined_results = []
        for benefit_id in all_benefit_ids:
            openai_benefit = next((b for b in openai_grouped if b["benefit_id"] == benefit_id), None)
            gemini_benefit = next((b for b in gemini_grouped if b["benefit_id"] == benefit_id), None)

            result = {
                "benefit_id": benefit_id,
                "openai_classification": {
                    "claims": [
                        {
                            "claim_id": c["claim_id"],
                            "service": c["service"],
                            "description": c["description"],
                            "amount": c["amount"],
                            "confidence": c["confidence"]
                        } for c in (openai_benefit["claims"] if openai_benefit else [])
                    ],
                    "average_confidence": openai_benefit["confidence"] if openai_benefit else 0
                },
                "gemini_classification": {
                    "claims": [
                        {
                            "claim_id": c["claim_id"],
                            "service": c["service"],
                            "description": c["description"],
                            "amount": c["amount"],
                            "confidence": c["confidence"]
                        } for c in (gemini_benefit["claims"] if gemini_benefit else [])
                    ],
                    "average_confidence": gemini_benefit["confidence"] if gemini_benefit else 0
                }
            }

            # Check for consensus
            if openai_benefit and gemini_benefit:
                openai_claim_ids = {c["claim_id"] for c in openai_benefit["claims"]}
                gemini_claim_ids = {c["claim_id"] for c in gemini_benefit["claims"]}
                consensus_claim_ids = openai_claim_ids.intersection(gemini_claim_ids)

                if consensus_claim_ids:
                    # Create a map of claim_id to confidence pairs from both models
                    openai_confidences = {c["claim_id"]: c["confidence"] for c in openai_benefit["claims"]}
                    gemini_confidences = {c["claim_id"]: c["confidence"] for c in gemini_benefit["claims"]}

                    consensus_claims = []
                    for claim_id in consensus_claim_ids:
                        claim_data = next(c for c in claims if c["claim_id"] == claim_id)
                        consensus_claim = {
                            "claim_id": claim_data["claim_id"],
                            "service": claim_data["service"],
                            "description": claim_data["description"],
                            "amount": claim_data["amount"],
                            "confidence": (openai_confidences[claim_id] + gemini_confidences[claim_id]) / 2
                        }
                        consensus_claims.append(consensus_claim)

                    result["consensus"] = {
                        "claims": consensus_claims,
                        "average_confidence": sum(c["confidence"] for c in consensus_claims) / len(consensus_claims)
                    }
                else:
                    result["consensus"] = None
            else:
                result["consensus"] = None

            combined_results.append(result)

        return combined_results

    async def classify_claims_thaisan(self, claim_info: Dict[str, Any],claims: List[dict], benefits_text: str) -> Dict[str, Any]:
        """Classify claims and group by benefits"""
        [openai_results, gemini_results] = await asyncio.gather(
            self.classify_with_openai_thaisan(claim_info, claims, benefits_text),
            self.classify_with_gemini(claims, benefits_text)
        )

        # Group results by benefit
        openai_grouped = self._group_by_benefit(claims, openai_results)
        gemini_grouped = self._group_by_benefit(claims, gemini_results)

        # Combine results
        all_benefit_ids = set(
            [b["benefit_id"] for b in openai_grouped] +
            [b["benefit_id"] for b in gemini_grouped]
        )

        combined_results = []
        for benefit_id in all_benefit_ids:
            openai_benefit = next((b for b in openai_grouped if b["benefit_id"] == benefit_id), None)
            gemini_benefit = next((b for b in gemini_grouped if b["benefit_id"] == benefit_id), None)

            result = {
                "benefit_id": benefit_id,
                "openai_classification": {
                    "claims": [
                        {
                            "claim_id": c["claim_id"],
                            "service": c["service"],
                            "description": c["description"],
                            "amount": c["amount"],
                            "confidence": c["confidence"]
                        } for c in (openai_benefit["claims"] if openai_benefit else [])
                    ],
                    "average_confidence": openai_benefit["confidence"] if openai_benefit else 0
                },
                "gemini_classification": {
                    "claims": [
                        {
                            "claim_id": c["claim_id"],
                            "service": c["service"],
                            "description": c["description"],
                            "amount": c["amount"],
                            "confidence": c["confidence"]
                        } for c in (gemini_benefit["claims"] if gemini_benefit else [])
                    ],
                    "average_confidence": gemini_benefit["confidence"] if gemini_benefit else 0
                }
            }

            # Check for consensus
            if openai_benefit and gemini_benefit:
                openai_claim_ids = {c["claim_id"] for c in openai_benefit["claims"]}
                gemini_claim_ids = {c["claim_id"] for c in gemini_benefit["claims"]}
                consensus_claim_ids = openai_claim_ids.intersection(gemini_claim_ids)

                if consensus_claim_ids:
                    # Create a map of claim_id to confidence pairs from both models
                    openai_confidences = {c["claim_id"]: c["confidence"] for c in openai_benefit["claims"]}
                    gemini_confidences = {c["claim_id"]: c["confidence"] for c in gemini_benefit["claims"]}

                    consensus_claims = []
                    for claim_id in consensus_claim_ids:
                        claim_data = next(c for c in claims if c["claim_id"] == claim_id)
                        consensus_claim = {
                            "claim_id": claim_data["claim_id"],
                            "service": claim_data["service"],
                            "description": claim_data["description"],
                            "amount": claim_data["amount"],
                            "confidence": (openai_confidences[claim_id] + gemini_confidences[claim_id]) / 2
                        }
                        consensus_claims.append(consensus_claim)

                    result["consensus"] = {
                        "claims": consensus_claims,
                        "average_confidence": sum(c["confidence"] for c in consensus_claims) / len(consensus_claims)
                    }
                else:
                    result["consensus"] = None
            else:
                result["consensus"] = None

            combined_results.append(result)

        return combined_results