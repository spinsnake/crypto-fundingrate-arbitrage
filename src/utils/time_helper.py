from datetime import datetime, timedelta, timezone
import time

class TimeHelper:
    @staticmethod
    def now_utc():
        return datetime.now(timezone.utc)

    @staticmethod
    def now_bkk():
        return TimeHelper.now_utc() + timedelta(hours=7)

    @staticmethod
    def now_bkk_str(fmt="%H:%M:%S"):
        return TimeHelper.now_bkk().strftime(fmt)

    @staticmethod
    def ms_to_bkk_str(ts_ms, fmt="%H:%M"):
        dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return (dt_utc + timedelta(hours=7)).strftime(fmt)

    @staticmethod
    def ms_to_mins_remaining(target_ms):
        now_ms = int(time.time() * 1000)
        diff_ms = target_ms - now_ms
        return max(0, int(diff_ms / 60000))
