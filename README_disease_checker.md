# Disease Drug Checker

Bộ công cụ để kiểm tra tên bệnh trong cột `indications_longchau` của bảng `drug_officially` trong PostgreSQL.

## Tính năng

- Tìm kiếm thuốc dựa trên tên bệnh
- Hỗ trợ 5 trường hợp tìm kiếm:
  1. `hỗ trợ điều trị` + tên bệnh
  2. `hỗ trợ và điều trị` + tên bệnh  
  3. `hỗ trợ` + tên bệnh
  4. `phòng ngừa và điều trị` + tên bệnh
  5. `dự phòng và điều trị` + tên bệnh
- Trích xuất context xung quanh tên bệnh
- Đếm số lượng thuốc tìm thấy
- Hỗ trợ async/await cho hiệu suất cao

## Cài đặt

1. Cài đặt các thư viện cần thiết:
```bash
pip install asyncpg python-dotenv
```

2. Cài đặt PostgreSQL và tạo database

3. Thiết lập biến môi trường:
```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/database_name"
```

## Sử dụng

### File đơn giản: `simple_disease_checker.py`

```python
import asyncio
from simple_disease_checker import check_disease_in_drugs, get_drug_count

async def main():
    # Tìm kiếm thuốc cho bệnh "viêm phế quản"
    disease_name = "viêm phế quản"
    
    # Lấy số lượng
    count = await get_drug_count(disease_name)
    print(f"Tìm thấy {count} thuốc")
    
    # Lấy chi tiết
    results = await check_disease_in_drugs(disease_name)
    
    for result in results:
        print(f"Thuốc: {result['name']}")
        print(f"Trường hợp match: {result['matched_case']}")
        print(f"Context: {result['context']}")

asyncio.run(main())
```

### File đầy đủ: `disease_drug_checker.py`

```python
import asyncio
from disease_drug_checker import DiseaseDrugChecker

async def main():
    checker = DiseaseDrugChecker()
    await checker.connect()
    
    try:
        # Kiểm tra bệnh
        results = await checker.check_disease_in_drugs("viêm phế quản")
        
        for result in results:
            print(f"ID: {result['id']}")
            print(f"Tên: {result['name']}")
            print(f"Trường hợp: {result['matched_case']}")
            print(f"Context: {result['matched_text']}")
            print("-" * 50)
            
    finally:
        await checker.close()

asyncio.run(main())
```

## Cấu trúc Database

Bảng `drug_officially` cần có các cột:
- `id`: ID của thuốc
- `name`: Tên thuốc
- `indications_longchau`: Mô tả chỉ định dài (chứa thông tin về bệnh)

## Ví dụ Output

```
Đang tìm kiếm thuốc cho bệnh: viêm phế quản
==================================================
Tìm thấy 15 thuốc

Chi tiết 5 thuốc đầu tiên:

1. Thuốc A
   Trường hợp match: 1
   Context: ...hỗ trợ điều trị các bệnh viêm phế quản, viêm phổi...

2. Thuốc B
   Trường hợp match: 2
   Context: ...hỗ trợ và điều trị viêm phế quản cấp và mãn tính...

... và 10 thuốc khác
```

## Lưu ý

- Sử dụng regex để tìm kiếm, đảm bảo tên bệnh được escape đúng cách
- Tìm kiếm không phân biệt chữ hoa/thường
- Context được trích xuất 100 ký tự trước và sau tên bệnh
- Hỗ trợ async/await để xử lý nhiều request đồng thời

## Xử lý lỗi

- Kiểm tra kết nối database trước khi sử dụng
- Xử lý các trường hợp tên bệnh không tìm thấy
- Log lỗi chi tiết để debug

## Tùy chỉnh

Bạn có thể thay đổi:
- Kích thước context trong hàm `extract_context`
- Thêm pattern tìm kiếm mới trong `_create_search_patterns`
- Thay đổi cấu trúc output theo nhu cầu
