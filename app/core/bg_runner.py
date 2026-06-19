import threading
import traceback

_shutdown_event = threading.Event()
_registry_lock = threading.Lock()
_running_jobs = {}


def clear_shutdown():
    _shutdown_event.clear()


def mark_shutdown():
    _shutdown_event.set()


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()


def start_daemon_job(name: str, func, *args, **kwargs) -> bool:
    """
    Start 1 daemon background job nếu job cùng tên chưa chạy.
    Return:
      True  -> job được start
      False -> đang shutdown hoặc job cùng tên đang chạy
    """
    if _shutdown_event.is_set():
        return False

    holder = {}

    def runner():
        try:
            func(*args, **kwargs)
        except Exception as e:
            print(f"[BG JOB:{name}] {type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            with _registry_lock:
                current = _running_jobs.get(name)
                if current is holder.get("thread"):
                    _running_jobs.pop(name, None)

    with _registry_lock:
        existing = _running_jobs.get(name)
        if existing and existing.is_alive():
            return False

        thread = threading.Thread(
            target=runner,
            daemon=True,
            name=f"bg::{name}",
        )
        holder["thread"] = thread
        _running_jobs[name] = thread
        thread.start()
        return True