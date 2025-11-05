#!/bin/bash

# File log đầu vào
LOG_FILE="logs_june.txt"
OUTPUT_FILE="ip_request_stats.txt"
DETAILED_FILE="june_detailed_requests.csv"

# Kiểm tra xem file log có tồn tại và có dữ liệu không
if [ ! -s "$LOG_FILE" ]; then
    echo "Lỗi: File $LOG_FILE rỗng hoặc không tồn tại" > $OUTPUT_FILE
    exit 1
fi

# Kiểm tra xem có request HTTP 200 OK nào không
if ! grep -q '"POST .* HTTP/1.1" 200 OK' "$LOG_FILE"; then
    echo "Không tìm thấy request HTTP 200 OK trong $LOG_FILE" > $OUTPUT_FILE
    exit 1
fi

# 1. Danh sách IP duy nhất
echo "Danh sách IP duy nhất:" > $OUTPUT_FILE
grep '"POST .* HTTP/1.1" 200 OK' "$LOG_FILE" | awk '{print $5}' | cut -d':' -f1 | sort -u >> $OUTPUT_FILE
echo "" >> $OUTPUT_FILE

# 2. Số lượng request mỗi IP/tháng
echo "Số lượng request mỗi IP trong tháng:" >> $OUTPUT_FILE
grep '"POST .* HTTP/1.1" 200 OK' "$LOG_FILE" | awk '{print $5}' | cut -d':' -f1 | sort | uniq -c | awk '{printf "%s: %s requests\n", $2, $1}' >> $OUTPUT_FILE
echo "" >> $OUTPUT_FILE

# 3. Số lượng request mỗi IP/ngày
echo "Số lượng request mỗi IP theo ngày:" >> $OUTPUT_FILE
grep '"POST .* HTTP/1.1" 200 OK' "$LOG_FILE" | awk '{print $3 " " $5}' | sed 's/\[//;s/|//' | cut -d'T' -f1 -s | awk '{print $2 " " $1}' | sort | uniq -c | awk '{printf "%s on %s: %s requests\n", $2, $3, $1}' >> $OUTPUT_FILE
echo "" >> $OUTPUT_FILE

# 4. Chi tiết request từng IP theo ngày (lưu vào CSV, bao gồm cột Date)
echo "Chi tiết request được lưu vào $DETAILED_FILE"
echo "Date,Timestamp,IP,Method,Endpoint,Status" > $DETAILED_FILE
grep '"POST .* HTTP/1.1" 200 OK' "$LOG_FILE" | awk '{print $3 " " $5 " " $7 " " $8 " " $10}' | sed 's/\[//;s/|//;s/"//g' | awk '{split($1, a, "T"); print a[1] "," $1 "," $2 "," $3 "," $4 "," $5}' >> $DETAILED_FILE