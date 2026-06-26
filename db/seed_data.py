"""Generate and insert mock operational data for development."""

from db.init_db import get_connection


def seed():
    """
    Populate tables with sample data.
    Pseudo-code:
      conn = get_connection()
      cursor = conn.cursor()
      cursor.executemany("INSERT INTO services (...) VALUES (...)", services)
      cursor.executemany("INSERT INTO incidents (...) VALUES (...)", incidents)
      cursor.executemany("INSERT INTO alerts (...) VALUES (...)", alerts)
      cursor.executemany("INSERT INTO runbooks (...) VALUES (...)", runbooks)
      conn.commit()
      conn.close()
    """
    conn = get_connection()
    cur = conn.cursor()

    services = [
        ("api-gateway",    "healthy"),
        ("auth-service",   "degraded"),
        ("payment-worker", "down"),
        ("notification",   "healthy"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO services (name, health) VALUES (?, ?)", services
    )

    incidents = [
        ("Payment worker timeout spike",      "critical", "open",   "High latency on /charge endpoint"),
        ("Auth token refresh failure",        "high",     "investigating", "5xx errors on /auth/refresh"),
        ("API gateway rate limiter blip",      "low",      "resolved", "Minor rate-limit threshold exceeded"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO incidents (title, severity, status, description) VALUES (?, ?, ?, ?)",
        incidents
    )

    alerts = [
        (2, "CPU > 90% on auth-pod-3",            "warning"),
        (3, "Payment queue depth > 1000",         "critical"),
        (1, "P99 latency > 500ms on /v1/orders",  "warning"),
    ]
    cur.executemany(
        "INSERT INTO alerts (service_id, message, level) VALUES (?, ?, ?)", alerts
    )

    runbooks = [
        ("High CPU on auth",          "1. Check pod logs\n2. Scale up replicas\n3. Review recent deploys",                                 "auth,cpu,scaling"),
        ("Payment queue backpressure", "1. Drain queue\n2. Restart worker\n3. Monitor DLQ",                                                 "payment,queue"),
        ("API gateway 5xx spike",     "1. Check backend health\n2. Verify rate limit config\n3. Rollback latest gateway release if needed", "gateway,5xx"),
    ]
    cur.executemany(
        "INSERT INTO runbooks (title, steps, tags) VALUES (?, ?, ?)", runbooks
    )

    conn.commit()
    conn.close()
    print("[Seed] Sample data inserted.")


if __name__ == "__main__":
    seed()
