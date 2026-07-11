import os
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__, template_folder="templates")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY environment variables are required.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ENTITY_CONFIG = {
    "departments": {
        "table": "departments",
        "allowed": {"name", "description"},
        "required": {"name"},
    },
    "positions": {
        "table": "positions",
        "allowed": {"title", "description", "department_id"},
        "required": {"title"},
    },
    "employees": {
        "table": "employees",
        "allowed": {
            "first_name",
            "last_name",
            "email",
            "phone",
            "profile_pic",
            "salary",
            "status",
            "department_id",
            "position_id",
            "hire_date",
        },
        "required": {"first_name", "last_name", "email"},
    },
    "attendance": {
        "table": "attendance",
        "allowed": {"employee_id", "date", "check_in", "check_out", "status"},
        "required": {"employee_id", "date"},
    },
    "leaves": {
        "table": "leaves",
        "allowed": {"employee_id", "start_date", "end_date", "type", "status", "reason"},
        "required": {"employee_id", "start_date", "end_date"},
    },
    "payroll": {
        "table": "payroll",
        "allowed": {
            "employee_id",
            "pay_period",
            "basic_salary",
            "allowances",
            "deductions",
            "net_salary",
            "status",
            "payment_date",
        },
        "required": {"employee_id", "pay_period", "basic_salary"},
    },
}


@app.after_request
def add_security_and_cors_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "JavaGoat HR"}), 200


@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    email = payload.get("email")
    password = payload.get("password")

    if email == "admin@javagoat.hr" and password == "password123":
        return jsonify(
            {
                "token": "mock-javagoat-hr-token",
                "user": {"email": "admin@javagoat.hr", "name": "JavaGoat Admin"},
            }
        )

    return jsonify({"error": "Invalid email or password"}), 401


def serialize_supabase_response(response):
    return response.data if response.data is not None else []


def clean_payload(entity, partial=False):
    cfg = ENTITY_CONFIG[entity]
    payload = request.get_json(silent=True) or {}

    if not isinstance(payload, dict):
        return None, "JSON object payload is required."

    cleaned = {}
    for key, value in payload.items():
        if key in cfg["allowed"]:
            cleaned[key] = normalize_value(key, value)

    if not partial:
        missing = [field for field in cfg["required"] if cleaned.get(field) in (None, "")]
        if missing:
            return None, f"Missing required field(s): {', '.join(missing)}"

    if partial and not cleaned:
        return None, "No valid fields supplied for update."

    if entity == "payroll":
        basic = float(cleaned.get("basic_salary") or 0)
        allowances = float(cleaned.get("allowances") or 0)
        deductions = float(cleaned.get("deductions") or 0)
        if "net_salary" not in cleaned or cleaned.get("net_salary") is None:
            cleaned["net_salary"] = round(basic + allowances - deductions, 2)

    return cleaned, None


def normalize_value(key, value):
    if value == "":
        return None

    integer_fields = {"employee_id", "department_id", "position_id"}
    decimal_fields = {"salary", "basic_salary", "allowances", "deductions", "net_salary"}

    if key in integer_fields:
        return int(value) if value is not None else None

    if key in decimal_fields:
        return float(value) if value is not None else 0

    return value


@app.route("/api/<entity>", methods=["GET", "POST", "OPTIONS"])
def entity_collection(entity):
    if request.method == "OPTIONS":
        return "", 204

    if entity not in ENTITY_CONFIG:
        return jsonify({"error": "Unknown entity."}), 404

    table = ENTITY_CONFIG[entity]["table"]

    try:
        if request.method == "GET":
            response = supabase.table(table).select("*").order("id", desc=False).execute()
            return jsonify(serialize_supabase_response(response))

        payload, error = clean_payload(entity, partial=False)
        if error:
            return jsonify({"error": error}), 400

        response = supabase.table(table).insert(payload).execute()
        rows = serialize_supabase_response(response)
        return jsonify(rows[0] if rows else {}), 201

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/<entity>/<int:item_id>", methods=["GET", "PUT", "DELETE", "OPTIONS"])
def entity_item(entity, item_id):
    if request.method == "OPTIONS":
        return "", 204

    if entity not in ENTITY_CONFIG:
        return jsonify({"error": "Unknown entity."}), 404

    table = ENTITY_CONFIG[entity]["table"]

    try:
        if request.method == "GET":
            response = supabase.table(table).select("*").eq("id", item_id).single().execute()
            return jsonify(response.data)

        if request.method == "PUT":
            # Crucial: partial update only. Fields not present in payload remain untouched.
            payload, error = clean_payload(entity, partial=True)
            if error:
                return jsonify({"error": error}), 400

            response = supabase.table(table).update(payload).eq("id", item_id).execute()
            rows = serialize_supabase_response(response)
            return jsonify(rows[0] if rows else {"id": item_id, **payload})

        response = supabase.table(table).delete().eq("id", item_id).execute()
        return jsonify({"deleted": True, "id": item_id, "data": serialize_supabase_response(response)})

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/dashboard/stats")
def dashboard_stats():
    try:
        departments = serialize_supabase_response(supabase.table("departments").select("*").execute())
        positions = serialize_supabase_response(supabase.table("positions").select("*").execute())
        employees = serialize_supabase_response(supabase.table("employees").select("*").execute())
        attendance = serialize_supabase_response(supabase.table("attendance").select("*").execute())
        leaves = serialize_supabase_response(supabase.table("leaves").select("*").execute())
        payroll = serialize_supabase_response(supabase.table("payroll").select("*").execute())

        dept_by_id = {row["id"]: row for row in departments}
        pos_by_id = {row["id"]: row for row in positions}

        active_leave_employee_ids = {
            row.get("employee_id")
            for row in leaves
            if str(row.get("status", "")).lower() == "approved"
        }

        payroll_total = sum(float(row.get("net_salary") or 0) for row in payroll)

        department_counter = Counter()
        for employee in employees:
            department = dept_by_id.get(employee.get("department_id"))
            department_counter[department["name"] if department else "Unassigned"] += 1

        status_counter = Counter(employee.get("status") or "Unknown" for employee in employees)

        hiring_counter = Counter()
        for employee in employees:
            hire_date = employee.get("hire_date")
            if hire_date:
                try:
                    hiring_counter[hire_date[:7]] += 1
                except Exception:
                    continue

        hiring_labels = last_n_month_labels(6)
        hiring_values = [hiring_counter.get(label, 0) for label in hiring_labels]

        attendance_labels = last_n_date_labels(7)
        attendance_counter = Counter()
        for row in attendance:
            row_date = row.get("date")
            status = str(row.get("status") or "").lower()
            if row_date and status in {"present", "late", "remote"}:
                attendance_counter[row_date[:10]] += 1

        employees_by_position = []
        for employee in employees:
            position = pos_by_id.get(employee.get("position_id"))
            employees_by_position.append(
                {
                    "id": employee.get("id"),
                    "name": f"{employee.get('first_name', '')} {employee.get('last_name', '')}".strip(),
                    "email": employee.get("email"),
                    "position": position["title"] if position else "Unassigned",
                    "profile_pic": employee.get("profile_pic"),
                }
            )

        response = {
            "cards": {
                "employees": len(employees),
                "departments": len(departments),
                "positions": len(positions),
                "on_leave": len(active_leave_employee_ids),
                "payroll_total": round(payroll_total, 2),
            },
            "hiring_trend": {
                "labels": hiring_labels,
                "values": hiring_values,
            },
            "department_mix": {
                "labels": list(department_counter.keys()) or ["No Data"],
                "values": list(department_counter.values()) or [0],
            },
            "employees_by_position": employees_by_position,
            "attendance_trend": {
                "labels": attendance_labels,
                "values": [attendance_counter.get(label, 0) for label in attendance_labels],
            },
            "status_breakdown": {
                "labels": list(status_counter.keys()) or ["No Data"],
                "values": list(status_counter.values()) or [0],
            },
        }

        return jsonify(response)

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def last_n_month_labels(n):
    today = date.today()
    labels = []
    year = today.year
    month = today.month

    for _ in range(n):
        labels.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return list(reversed(labels))


def last_n_date_labels(n):
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in reversed(range(n))]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
