import json, logging, time

log = logging.getLogger("audit")

class AuditLogger:
    def log_order(self, order_id: str, action: str, details: dict):
        entry = {
            "ts": int(time.time() * 1000),
            "order_id": order_id,
            "action": action,
            **details,
        }
        log.info(json.dumps(entry))

    def log_immunity_block(self, reason: str, order: dict):
        log.warning(json.dumps({"ts": int(time.time() * 1000), "BLOCKED": reason, "order": order}))
