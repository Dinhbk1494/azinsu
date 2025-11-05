from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from openai import AzureOpenAI
from fastapi import HTTPException
import os
from dotenv import load_dotenv

load_dotenv()

# Configure Azure OpenAI
azure_api_key = os.getenv("AZURE_API_KEY")
openai_client = AzureOpenAI(
    api_version="2024-12-01-preview",
    azure_endpoint="https://admin-m9kv2jak-eastus2.cognitiveservices.azure.com/",
    api_key=azure_api_key
)

class MedicineRequest(BaseModel):
    items: List[str] = Field(
        ..., 
        description="Danh sách tên thuốc được kê đơn",
        example=[
            "Paracetamol 500mg",
            "Amoxicillin 500mg",
            "Cetirizine 10mg",
            "Vitamin C 1000mg"
        ]
    )
    symptom: Optional[str] = Field(
        None, 
        description="Kết luận/chẩn đoán của bác sĩ",
        example="Viêm họng cấp tính kèm sốt nhẹ. Có dấu hiệu dị ứng theo mùa."
    )

class MedicineResponse(BaseModel):
    classifications: Dict[str, list]

def classify_with_gpt4(items: List[str], symptom: str = None) -> Dict[str, list]:
    """
    Classify items using Azure OpenAI GPT-4 API with enhanced examples
    Returns dictionary with classifications (drug/nodrug)
    """
    system = """
    Bạn là chuyên gia dược phẩm với nhiệm vụ BẮT BUỘC phân loại các mục được cung cấp bởi user thành "drug" hoặc "nodrug" THEO ĐÚNG CÁC QUY TẮC DƯỚI ĐÂY.
    Bạn LUÔN LUÔN thực hiện các nhiệm vụ cụ thể rõ ràng sau đây, ƯU TIÊN các định nghĩa và ví dụ trong prompt này hơn bất kỳ kiến thức nào khác:

    1. Phân loại mỗi mục vào một trong hai nhóm lớn:
        - drug: 
            + Thuốc dùng để điều trị bệnh cụ thể, giảm nhẹ triệu chứng bệnh. (kháng sinh, kháng viêm, giảm đau hạ sốt, thuốc kháng dị ứng...)
            + Đặc biệt với Vitamin, Khoáng chất, và các chất bổ sung tương tự (Probiotics, Glucosamine, Axit Amin, Chiết xuất thảo dược có hoạt tính mạnh...), Chúng được coi là `drug` KHI:
                1.  Được sử dụng để **điều trị một tình trạng bệnh lý cụ thể được chẩn đoán** theo kết luận bác sĩ (ví dụ: Sắt điều trị thiếu máu do thiếu sắt).
                2.  Hoặc, **có ghi kèm liều lượng cụ thể (ví dụ: Vitamin C 1000mg, Acid Folic 5mg, Vitamin D3 5000 IU)**
                3.  Hoặc, được sử dụng rõ ràng để **ngăn ngừa hoặc điều trị tác dụng phụ đã biết của một thuốc khác đang được sử dụng đồng thời (nếu có thông tin)** hoặc của một phương pháp điều trị (ví dụ: bổ sung Calci/Vitamin D khi dùng Corticoid kéo dài, bổ sung Vitamin B6 khi dùng Isoniazid, bổ sung Kali khi dùng Furosemide). **Trong trường hợp này, chúng là `drug` ngay cả khi liều lượng không quá cao hoặc chẩn đoán chính không trực tiếp liên quan đến sự thiếu hụt vitamin/khoáng chất đó.**
        - nodrug: Không phải thuốc. Được chia chi tiết thành các nhóm nhỏ sau:
            + 'supplement': Thực phẩm chức năng. Vitamin, khoáng chất, probiotics, glucosamine, thảo dược... sử dụng với mục đích **bổ sung dinh dưỡng thông thường, duy trì sức khỏe chung, phòng ngừa thiếu hụt không đặc hiệu.** 
            + 'medical supplies': Vật tư y tế, dụng cụ y tế, trang thiết bị y tế (kim tiêm, nhiệt kế, khẩu trang, chỉ khâu y tế, bông gòn y tế...)
            + 'cosmeceuticals': Sản phẩm kết hợp giữa mỹ phẩm và dược phẩm, có tác dụng làm đẹp và hỗ trợ điều trị da
            + 'medical equipment': Thiết bị máy móc y tế, dụng cụ dùng cho chẩn đoán, điều trị, phòng bệnh, hỗ trợ chức năng cơ thể
            + 'other': những thứ không xác định rõ, từ ngữ ngẫu nhiên hay một từ vô nghĩa (abc, 8y7, đi chơi...)

    2. Với các mục 'drug', bạn thực hiện thêm nhiệm vụ đánh giá:
        - Tính hợp lệ (valid/invalid) dựa vào bệnh có kết luận của bác sĩ.
            + Nếu có kết luận, 'valid' khi thuốc và chuẩn đoán của bác sĩ là phù hợp
            + Nếu có kết luận, 'invalid' khi thuốc và chuẩn đoán của bác sĩ là không phù hợp
            + Nếu không có kết luận bác sĩ, thì tất cả các drug luôn mặc định valid.
        - Thuốc chính 'main drug' hay thuốc hỗ trợ 'secondary drug':
            + 'main drug': Chuẩn đoán bác sĩ sẽ có thể có nhiều bệnh, do đó nếu Thuốc trực tiếp điều trị ít nhất một trong những nguyên nhân hoặc triệu chứng của một bệnh sẽ được coi là thuốc chính (ví dụ: thuốc chống co thắt trong bệnh cấp tính, Enterogermina cho bệnh tiêu hóa,...). Với trường hợp chẩn đoán nhiều bệnh, chỉ cần có hiệu quả với 1 bệnh cũng được coi là thuốc chính.
            + 'main drug': tất cả các loại thuốc sẽ có xu hướng là thuốc chính, trừ khi có những bằng chứng cụ thể về việc nó là 'secondary drug'.
            + 'main drug': nếu bệnh nhân bị viêm, mổ hay bị đau, thì các loại thuốc giảm đau, thuốc sát khuẩn đều là thuốc chính.
            + 'main drug': Nếu thuốc là vitamin kết hợp với loại khác (ví dụ: Nhôm hydroxyd + Magnesium hydroxide) thì sẽ coi là thuốc chính. 
            + 'main drug': Nếu vitamin hay thành phần chính là vitamin, nhưng chẩn đoán bác sĩ có liên quan thiếu vitamin hay điện giải thì lúc này đây được coi là thuốc chính.
            + 'secondary drug': Thuốc không điều trị trực tiếp của bệnh hay triệu chứng nào trong kết luận bác sĩ, nhưng hỗ trợ tác dụng của 'main drug' hoặc giảm tác dụng phụ của thuốc khác. 
            + 'secondary drug': Nếu bệnh không liên quan đến thiếu trực tiếp vitamin, thì Vitamin sẽ chắc chắn là thuốc hỗ trợ này.
            + Nếu không có kết luận bác sĩ, bạn sẽ tự xác định theo hiểu biết y dược.
    3. Xử lý Thuốc Đông y/Thảo dược (không phải dạng bổ sung thông thường):
        - Nếu tên thuốc là một vị thuốc Đông y cụ thể hoặc một bài thuốc cổ truyền (ví dụ: Ngưu tất, Độc hoạt tang ký sinh, Boganic) VÀ "kết luận bác sĩ" có bệnh lý mà thuốc này thường được dùng để điều trị (ví dụ: "Thoái hóa khớp gối" cho Ngưu tất), thì phân loại là: `[Tên Đông y] -> drug -> valid -> main drug` (hoặc `secondary drug` tùy vai trò).
        - Nếu không có hoặc "kết luận bác sĩ" không liên quan, có thể xem xét là `nodrug -> supplement` (nếu mang tính bồi bổ chung).
    Lưu ý đặc biệt:
    - **kết luận bác sĩ là cơ sở quan trọng nhất** để phân loại
    - Tất cả các loại thuốc được kê có xu hướng đều là 'main drug', do đó nếu không có chứng cứ rõ ràng một loại thuốc nào đó thuộc 'secondary drug, thì hãy coi nó là 'main drug'.
    - Nhiều khả năng 1 đơn thuốc chỉ chứa thuốc chính 'main drug' mà không có thuốc hỗ trợ 'secondary drug'.
    Luôn trả lời đúng theo format sau:

    Đối với drug:
    [tên] -> drug -> [valid/invalid] -> [main drug/secondary drug]

    Đối với nodrug:
    [tên] -> nodrug -> [supplement/medical supplies/other]

    Các ví dụ minh họa cụ thể:

    Ví dụ 1:
    Input:
    a, Kết luận bác sĩ: Đau đầu căng thẳng
    b, Thuốc:
    - Paracetamol
    - Vitamin C
    - Omega 3
    - khẩu trang y tế
    - 789xyz

    Output:
    Paracetamol -> drug -> valid -> main drug
    Vitamin C -> drug -> valid -> secondary drug
    Omega 3 -> drug -> valid -> secondary drug
    khẩu trang y tế -> nodrug -> medical supplies
    789xyz -> nodrug -> other

    Ví dụ 2:
    Input:
    a, Kết luận bác sĩ: Dị ứng theo mùa, đau bụng khó chịu
    b, Thuốc:
    - Cetirizine
    - Loratadine
    - Bacillus Clausii (Enterogermina 2 tỷ/5ml)

    Output:
    Cetirizine -> drug -> valid -> main drug
    Loratadine -> drug -> valid -> main drug
    Bacillus Clausii (Enterogermina 2 tỷ/5ml) -> drug -> valid -> main drug

    Ví dụ 3:
    Input:
    a, Kết luận bác sĩ: Không có kết luận bác sĩ
    b, Thuốc:
    - Omeprazole
    - Magnesium
    - Giấy lau cồn y tế

    Output:
    Omeprazole -> drug -> valid -> main drug
    Magnesium -> drug -> valid -> secondary drug
    Giấy lau cồn y tế -> nodrug -> medical supplies

    Ví dụ 4:
    Input:
    a, Kết luận bác sĩ: Bệnh nhân đái tháo đường type 2, tăng huyết áp vô căn, suy giảm sức đề kháng, đau nhức khớp tuổi già, rối loạn lipid máu nhẹ.
    b, Thuốc và sản phẩm:
    - Metformin
    - Losartan
    - Atorvastatin
    - Paracetamol
    - Ibuprofen
    - Aspirin
    - Glucosamine Sulfate 1500mg
    - Vitamin D3 2000 IU
    - Omega 3 (viên nang, 1000mg)
    - Máy đo đường huyết cá nhân
    - Kim lấy máu máy đo đường huyết

    Output:
    Metformin -> drug -> valid -> main drug
    Losartan -> drug -> valid -> main drug
    Atorvastatin -> drug -> valid -> main drug
    Paracetamol -> drug -> valid -> main drug
    Ibuprofen -> drug -> valid -> main drug
    Aspirin -> drug -> valid -> main drug
    Glucosamine Sulfate 1500mg -> drug -> valid -> main drug 
    Vitamin D3 2000 IU -> drug -> valid -> secondary drug
    Omega 3 (viên nang, 1000mg) -> drug -> valid -> secondary drug
    Máy đo đường huyết cá nhân -> nodrug -> medical supplies
    Kim lấy máu máy đo đường huyết -> nodrug -> medical supplies

    Ví dụ 5 (Nhiều bệnh, có mã ICD):
    Input:
    a, Kết luận bác sĩ: Tăng huyết áp vô căn (I10), Đái tháo đường type 2, không biến chứng (E11.9), Viêm khớp dạng thấp (M06.9), Rối loạn giấc ngủ không thực tổn (F51.0)
    b, Thuốc & sản phẩm:
    - Losartan 50mg
    - Metformin 500mg
    - Insulin Glargin
    - Meloxicam 7.5mg
    - Methotrexate
    - Prednisone
    - Zolpidem 5mg
    - Vitamin B-complex
    - Curcumin (viên 500mg)
    - Đai cố định khớp gối
    - Máy đo huyết áp điện tử Omron

    Output:
    Losartan -> drug -> valid -> main drug
    Metformin -> drug -> valid -> main drug
    Insulin Glargin -> drug -> valid -> main drug
    Meloxicam -> drug -> valid -> main drug
    Methotrexate -> drug -> valid -> main drug
    Prednisone -> drug -> valid -> secondary drug
    Zolpidem -> drug -> valid -> main drug
    Vitamin B-complex (Scanneuron, 1 viên) -> drug -> valid -> secondary drug
    Curcumin (viên 500mg) -> drug -> valid -> secondary drug
    Đai cố định khớp gối -> nodrug -> medical supplies
    Máy đo huyết áp điện tử Omron -> nodrug -> medical supplies

    """
    user1 ="""
    a, Kết luận bác sĩ: Người cao tuổi mắc COVID-19 thể nhẹ, đau họng, sốt, đau đầu, chảy nước mũi, thiếu vitamin và khoáng chất, mất ngủ nhẹ kèm lo âu.
    b, Thuốc và sản phẩm:
    - Paracetamol
    - Ibuprofen
    - Ambroxol
    - Cetirizine
    - Diazepam
    - Vitamin C 1000mg
    - Kẽm (Zinc)
    - Magie (Magnesium)
    - Khẩu trang N95
    - Nước muối sinh lý 0.9% NaCl
    - Máy đo SpO2 cá nhân
    - Xịt họng keo ong thảo dược
    - asdk88
    """
    assistant1 = """
    Paracetamol -> drug -> valid -> main drug
    Ibuprofen -> drug -> valid -> secondary drug
    Ambroxol -> drug -> valid -> secondary drug
    Cetirizine -> drug -> valid -> secondary drug
    Diazepam -> drug -> valid -> secondary drug
    Vitamin C 1000mg -> nodrug -> supplement
    Kẽm (Zinc) -> nodrug -> supplement
    Magie (Magnesium) -> nodrug -> supplement
    Khẩu trang N95 -> nodrug -> medical supplies
    Nước muối sinh lý 0.9% NaCl -> nodrug -> medical supplies
    Máy đo SpO2 cá nhân -> nodrug -> medical supplies
    Xịt họng keo ong thảo dược -> nodrug -> supplement
    asdk88 -> nodrug -> other
    """
    user2 ="""
    a, Kết luận bác sĩ: Viêm loét dạ dày tá tràng, có chảy máu nhẹ (K25.4), Gan nhiễm mỡ độ II, Hen phế quản dị ứng (J45.0), Cơn đau đầu Migraine không kèm aura (G43.0), Thiếu chất dinh dưỡng, thiếu vi chất
    b, Thuốc & sản phẩm:
    - Omeprazole 20mg
    - Sucralfate
    - Salbutamol dạng xịt
    - Budesonide
    - Paracetamol 500mg
    - Sumatriptan 50mg
    - Vitamin C hàm lượng cao 1000mg
    - Silymarin thảo dược hỗ trợ gan
    - Viên uống Iron bổ sung sắt
    - Ống hít định liều (ống hít cá nhân cho hen suyễn)
    - Máy đo chức năng hô hấp
    - Kim luồn tĩnh mạch 22G
    """
    assistant2 = """
    Omeprazole -> drug -> valid -> main drug
    Sucralfate -> drug -> valid -> secondary drug
    Salbutamol dạng xịt -> drug -> valid -> main drug
    Budesonide -> drug -> valid -> secondary drug
    Paracetamol -> drug -> valid -> secondary drug
    Sumatriptan -> drug -> valid -> main drug
    Vitamin C hàm lượng cao 1000mg -> nodrug -> supplement
    Silymarin thảo dược hỗ trợ gan -> nodrug -> supplement
    Viên uống Iron bổ sung sắt -> nodrug -> supplement
    Ống hít định liều (ống hít cá nhân cho hen suyễn) -> nodrug -> medical supplies
    Máy đo chức năng hô hấp -> nodrug -> medical supplies
    Kim luồn tĩnh mạch 22G -> nodrug -> medical supplies
    """
    prompt1 = """
    a, Kết luận bác sĩ: Viêm họng cấp tính kèm sốt nhẹ. Có dấu hiệu dị ứng theo mùa.
    b, Thuốc: 
    - Paracetamol 500mg
    - Amoxicillin 500mg
    - Cetirizine 10mg
    - Vitamin C 1000mg
    - khẩu trang y tế 4 lớp
    - 9kdfj3
    """

    formatted_items = "\n- ".join([item.strip() for item in items])
    if symptom:
        prompt = f"a, Kết luận bác sĩ: {symptom}\nb, Thuốc: \n- {formatted_items}\n"
    else:
        prompt = f"a, Kết luận bác sĩ: bệnh nhân chưa có hướng điều trị\nb, Thuốc: \n- {formatted_items}\n"
    try:
        messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Ensure this is the correct deployment name in Azure
            messages=messages,
            temperature=0
        )
        # Process Azure OpenAI response
        response_text = response.choices[0].message.content
        print("response_text: ", response_text)
        classifications = {}
        
        # Parse response and create dictionary
        for line in response_text.strip().split('\n'): 
            if '->' in line:
                item = line.split('->')
                if len(item) == 4 or len(item) == 3:
                    classifications[item[0].strip()] = [e.strip() for e in item[1:]]
        return classifications
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Azure OpenAI Classification error: {str(e)}")