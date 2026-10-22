# Thử tối ưu kiểm kê — 22/10/2026

## Phạm vi

Nhánh thử; chưa bật production. Hai cờ mới mặc định tắt: refresh=0 và
checkpoint=1. Lịch, thời gian chạy, đường tải original, collision/hash, upload,
remote-size verification và checkpoint mỗi 10 media đều giữ nguyên.

1. Chỉ hoãn quét lại nếu tất cả nguồn đã duyệt xong, có timestamp hoàn tất hợp lệ
   dưới 24 giờ, và manifest vẫn có mục chưa uploaded. Luôn tiếp tục nguồn đang dở.
   Hết backlog, timestamp cũ/thiếu/sai/tương lai đều phải quét lại. Daily mặc định
   vẫn quét. Đây là TTL của lượt kiểm kê hoàn tất, không phải chứng nhận đủ bản gốc.
2. Gom checkpoint kiểm kê tối đa 10 trang hoặc 60 giây; lỗi nguồn và cuối lượt đều
   flush. Timestamp hoàn tất đi cùng cursor trong snapshot SQLite. Không gom các
   thao tác xác minh từng media. Không có tải/upload media trong pha inventory.

60 giây là khoảng kiểm tra giữa các trang, không phải giới hạn cứng nếu một RPC
bị treo. Checkpoint từ xa lỗi vẫn chặn như hiện tại. Hard kill có thể phải quét lại
những trang chưa gửi checkpoint (thông thường tối đa 9 trang thành công sau mốc
cuối), không mất file ảnh. Stop bình thường vẫn lưu state qua finally của worker.
Mỗi snapshot vẫn dùng SQLite Backup API. Không thêm writer chạy song song.

## Thử nghiệm đã thực hiện

69 tests pass, gồm 9 test mới: TTL hết hạn/thiếu/sai/tương lai; mặc định Daily;
hết backlog; nguồn lỗi; cursor dở; bản snapshot thực SQLite; ngắt cứng; ngưỡng 60 giây; A/B cùng
100 trang và cùng IDs.

A/B: checkpoint mỗi trang = 101 snapshot; gom 10 trang = 11 snapshot; gồm snapshot
cuối ghi timestamp. Final web_items và cursor giống hệt. Mỗi flush hiện upload
2 file state nên tương ứng 202 → 22 thao tác copyto state trong fixture.
Không suy ra tăng tốc upload 89%, không đo băng thông hoặc thời gian Google/Koofr.

## Chạy thử thực tế

Backfill workflow có input `inventory_speed_trial`, boolean mặc định false, chỉ
bật tay cho một lượt. Schedule vẫn dùng baseline. Với thử ngắn, max_items=20.
Worker dùng concurrency group hiện có; không chạy writer độc lập hoặc reset state.
Lượt thử thật vẫn backup media vào kho hiện hành và lưu manifest/profile như một
lượt backup bình thường; không tạo bản sao độc lập, không sửa/xóa file cũ.

Cờ runtime tương đương:

```sh
python3 -m src.gphotos_web_backup --scan-seconds 600 --maxitems 20 --inventory-refresh-seconds 86400 --inventory-checkpoint-pages 10
```

Chỉ chạy trong môi trường workflow có config và phiên đã khôi phục. Không chạy
lệnh này từ checkout thiếu config. Không in cookies hoặc đưa credentials vào log.
`INVENTORY_PERF` ghi pages, remote_checkpoints, seconds. `INVENTORY_DEFERRED` nói
rõ có hoãn quét vì vòng gần đây hoàn tất và còn backlog. WEB_SUMMARY giữ schema cũ.

Chưa có lượt thử live hoặc benchmark Google/Koofr. Không cộng các file khác nhau
rồi coi là A/B về tốc độ. Khi áp dụng, so cùng dữ liệu thử riêng hoặc nhiều lượt
có phân bố ảnh/video tương đương; đo GB/h và errors, không chỉ mục/h. Khả năng
hoãn quét có thể ít tác dụng nếu Daily đã mở một vòng kiểm kê mới còn dở trước
Backfill. Nếu thời gian kiểm kê chỉ chiếm phần nhỏ, mức tăng tổng thể sẽ nhỏ.
