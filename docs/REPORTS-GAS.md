# Báo cáo Photos Daily qua GAS/Drive

Đối chiếu source workflow và hồ sơ phục hồi ngày 22/10/2026; không chạy backup,
probe hoặc publish mới trong đợt cập nhật tài liệu.

## Cấu hình và ranh giới

- Workflow mặc định `REPORT_BACKEND=gas-drive`; variable `REPORT_GAS_URL`,
  secret `REPORT_GAS_KEY` riêng cho source `gphotos`.
- `scripts/publish_gas_report.py` ký HMAC, xác minh signed ACK, giữ nguyên
  run ID/number/attempt và mutation identity khi retry. Không reset HEAD/sequence.
- Backend GAS reporting khác GAS chi tiêu/Gemini và GAS webhook bot.
- Blob là đường legacy chọn tường minh; không tự fallback, không phải backend
  Homepage đang chọn. Không cấp lại key hay chuyển về Blob theo tài liệu cũ.
- Publish lỗi được tách khỏi kết quả engine; badge xanh không chứng minh báo cáo
  đã đến nơi hoặc toàn bộ dữ liệu đã backup. Không có raw log/tên file/token trong feed.
- Feed Daily không nhận Backfill/Reconcile. Backfill dùng [nhánh aggregate riêng](BACKFILL-PROGRESS-20261022.md).

## Bằng chứng và kiểm tra

Ngày 20/10 đã xác minh signed ACK và hai API HTTP 200 bằng báo cáo thật có
run ID/thời gian gốc; không chạy lại engine để phục hồi feed.
[Bằng chứng đầy đủ, gồm các lỗi đã khắc phục](https://github.com/hunghvt-cyber/Homepage-nas/blob/main/docs/results/backup-report-recovery-20261020.md).
Không coi lỗi NO_REPORT hoặc thiếu handler GAS v12 trong hồ sơ cũ là trạng thái mới.

Kiểm tra fixture: `python3 -m unittest discover -s tests -p 'test_report*.py'`.
Đọc workflow và bộ test hiện có trước khi chạy; fixture không chứng minh media backup.

Hợp đồng/API và vận hành chung thuộc
[Homepage OPERATIONS](https://github.com/hunghvt-cyber/Homepage-nas/blob/main/docs/OPERATIONS.md);
thiết kế ban đầu ở [BACKUP-REPORTS-GAS-20261018](https://github.com/hunghvt-cyber/Homepage-nas/blob/main/docs/BACKUP-REPORTS-GAS-20261018.md).
Không sửa config, secret, lịch hoặc dữ liệu trong một đợt tài liệu.
