import queue
import threading
import time

job_queue = queue.Queue(maxsize=200)

def worker_routine():
    while True:
        try:
            # ====================================================
            # KHUNG THOÁT HIỂM (CIRCUIT BREAKER) CHỐNG TRÀN HÀNG ĐỢI
            # ====================================================
            if job_queue.qsize() > 150:
                print("[Escape Hatch] CẢNH BÁO: Hàng đợi quá tải (>150 tasks). Tự động xả tải để tránh tràn RAM!")
                with job_queue.mutex:
                    job_queue.queue.clear()
            
            task = job_queue.get(timeout=1.0)
            if task is None:
                break
            
            task_type = task.get("type")
            payload = task.get("payload", {})
            
            try:
                # Mô phỏng xử lý ghi cơ sở dữ liệu hoặc đồng bộ Cloud
                time.sleep(0.02)  
            except Exception as e:
                print(f"[Worker Error] Lỗi xử lý {task_type}: {e}")
            
            job_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[Worker Loop Error] {e}")

_worker_thread = threading.Thread(target=worker_routine, daemon=True)
_worker_thread.start()

def enqueue_work(task_type, payload):
    try:
        job_queue.put_nowait({"type": task_type, "payload": payload})
    except queue.Full:
        pass  # Drop request nếu hàng đợi đầy, bảo vệ luồng realtime
