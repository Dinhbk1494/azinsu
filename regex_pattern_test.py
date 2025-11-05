import re
from typing import List, Dict, Union
import pandas as pd


def match_patterns(patterns: Union[List[str], Dict[str, str]], text: str,  context: int = 10):
    """
    Kiểm tra text với nhiều regex pattern.

    :param patterns: 
        - Nếu là list: ["pat1", "pat2", ...]
        - Nếu là dict: {"label1": "pat1", "label2": "pat2", ...}
    :param text: Chuỗi cần kiểm tra.
    :return: dict kết quả
    """
    results = []
    
    # Nếu patterns là list, convert thành dict tạm với label = pattern
    if isinstance(patterns, list):
        patterns = {p: p for p in patterns}
    
    for label, pat in patterns.items():
        regex = re.compile(pat)
        matches = regex.finditer(text)
        if matches:
            for m in matches:
                # Nếu pattern có group, findall trả tuple => lấy group 0
                # match_text = m if isinstance(m, str) else m[0]
                start, end = m.span()
                match_text = text[start:end]
                before = text[max(0, start - context): start]
                after = text[end: min(len(text), end + context)]
                results.append({
                    "label": label,
                    "pattern": pat,
                    "match_text": match_text,
                    "context": before + match_text + after,
                })
    
    return {
        "matched": bool(results),
        "matched_count": len(results),
        "matches": results
    }
    
if __name__ == "__main__": 
    patterns = {
        "treat": r"(điều\s*trị|chữa\s*trị|trị\s*liệu)",
        "prevent": r"(phòng\s*ngừa|đề\s*phòng)",
        "disease": r"(đau\s*họng|cảm\s*cúm| CHỈ ĐỊNH)"
    }

    text = """CHỈ ĐỊNH

Thuốc Fexofenadine Hydrochloride 180mg
[https://nhathuoclongchau.com.vn/thuoc/fexofenadine-hydrochloride-180-mg-an-thien-3-x10.html]
dùng ở người lớn và trẻ em từ 12 tuổi trở lên để:

 * Điều trị triệu chứng trong viêm mũi dị ứng đau họng
   [https://nhathuoclongchau.com.vn/benh/viem-mui-di-ung-473.html] theo mùa: Hắt
   hơi, chảy nước mũi, ngứa mũi, chảy nước mắt, đỏ mắt, ngứa vòm miệng và họng.
 * Điều trị triệu chứng trong mày đay mạn tính vô căn: Ngứa, nổi mẫn đỏ.


DƯỢC LỰC HỌC

Nhóm dược lý: Kháng histamin thế hệ 2, đối kháng thụ thể H1.

Mã ATC: R06AX26.

Fexofenadin là thuốc kháng histamin thế hệ 2
[https://nhathuoclongchau.com.vn/bai-viet/thuoc-khang-histamin-h2-duoc-dung-de-dieu-tri-benh-gi.html],
có tác dụng đối kháng đặc hiệu và chọn lọc trên thụ thể H1 ngoại vi. Thuốc là
một chất chuyển hóa có hoạt tính của terfenadin, cũng cạnh tranh với histamin
tại các thụ thể H1 ở đường tiêu hóa, mạch máu và đường hô hấp, nhưng không có
độc tính đối với tim do không ức chế kênh kali liên quan đến sự tái cực tế bào
cơ tim.

Fexofenadin không có tác dụng đáng kể đối kháng acetylcholin, đối kháng dopamin
và không có tác dụng ức chế thụ thể a1 hoặc ß-adrenergic. Ở liều điều trị, thuốc
không gây ngủ hay ảnh hưởng đến TKTW. Thuốc có tác dụng nhanh và kéo dài do
thuốc gắn chậm vào thụ thể H1, tạo thành phức hợp bền vững và tách ra chậm.


DƯỢC ĐỘNG HỌC

Hấp thu

Thuốc hấp thu tốt khi dùng đường uống và bắt đầu phát huy tác dụng sau khi uống
60 phút. Nồng độ đỉnh trong máu đạt được sau 2 - 3 giờ. Thức ăn giàu chất béo
làm giảm nồng độ đỉnh trong huyết tương khoảng 17% và kéo dài thời gian đạt nồng
độ đỉnh của thuốc (đến khoảng 4 giờ). Tác dụng kháng histamin kéo dài hơn 12
giờ.

Phân bố

Tỷ lệ liên kết với protein huyết tương của thuốc là 60 - 70%, chủ yếu là albumin
và α1-acid glycoprotein.

Không rõ thuốc có qua nhau thai hoặc bài tiết vào sữa mẹ hay không, nhưng khi
dùng terfenadin đã phát hiện được fexofenadin là chất chuyển hóa của terfenadin
trong sữa mẹ. Fexofenadin không qua hàng rào máu - não.

Chuyển hóa

Fexofenadin rất ít bị chuyển hóa (khoảng 5%, chủ yếu ở niêm mạc ruột, chỉ có
khoảng 0,5 - 1,5% được chuyển hóa ở gan nhờ hệ enzym cytochrom P450 thành chất
không có hoạt tính). Khoảng 3,5% liều fexofenadin chuyển hóa qua pha II (không
liên quan đến hệ enzym cytochrom P450) thành dẫn chất methyl este. Chất chuyển
hóa này chỉ thấy ở trong phân nên có thể có sự tham gia của các vi khuẩn đường
ruột vào chuyển hóa này.

Thải trừ

Thời gian bán thải của fexofenadin khoảng 14,4 giờ, kéo dài hơn (31 - 72%) ở
người suy thận. Thuốc thải trừ chủ yếu qua phân (xấp xỉ 80%) và nước tiểu (11 -
12%) dưới dạng không đổi.

Dược động học ở người suy thận

 * Clcr 41 - 80 ml/phút: Nồng độ đỉnh cao hơn 87%, thời gian bán thải dài hơn
   59%.
 * Clcr 11 - 40 ml/phút: Nồng độ đỉnh cao hơn 111%, thời gian bán thải dài hơn
   72%.
 * Clcr < 10 ml/phút (ở người đang thực hiện thẩm phân): Nồng độ đỉnh cao hơn
   82% và thời gian bán thải dài hơn 31% so với người khỏe mạnh."""

    result = match_patterns(patterns, text)
    print("Result:", result)

    # from pprint import pprint
    # pprint(result)
# đock từ csv tên aâ.csv sheet name 'aaa' cột 'use_longchau
#tìm xem regex pattern nào khớp với cột use_longchau'
data = pd.read_excel('drugs_officially_rows_short.xlsx', sheet_name='Sheet2')
# Tạo 4 cột trống ban đầu
data["label"] = ""
data["pattern"] = ""
data["match_text"] = ""
data["context"] = ""
for i, row in data.iterrows():
    text = row['indications_longchau'] or ''
    print("texxt: ", text)
    if pd.isna(text):   # NaN thì thay bằng chuỗi rỗng
        text = ''
    else:
        text = str(text).strip()
    
    if text == '':
        continue

    result = match_patterns(patterns, text)
    if result['matched']:
        print(f"Row {i} matched patterns: {result['matches']}")
    if result["matched"]:
        # Ghép nhiều match (nếu có)
        labels = "; ".join([m["label"] for m in result["matches"]])
        patterns_str = "; ".join([m["pattern"] for m in result["matches"]])
        match_texts = "; ".join([m["match_text"] for m in result["matches"]])
        contexts = "; ".join([m["context"] for m in result["matches"]])

        # Ghi vào DataFrame
        data.at[i, "label"] = labels
        data.at[i, "pattern"] = patterns_str
        data.at[i, "match_text"] = match_texts
        data.at[i, "context"] = contexts

# Xuất ra file Excel mới để kiểm tra
data.to_excel("drugs_with_matches.xlsx", index=False)
    


