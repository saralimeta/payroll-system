import streamlit as st
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta, time
from typing import NamedTuple, List

st.set_page_config(page_title="Schedule Generator", layout="wide")

# ---- shift logic ----
class Shift(NamedTuple):
    id: str
    start: time

SHIFTS: List[Shift] = [
    Shift("06-15", time(6, 0)),
    Shift("07-16", time(7, 0)),
    Shift("08-17", time(8, 0)),
    Shift("09-18", time(9, 0)),
    Shift("10-19", time(10, 0)),
    Shift("12-21", time(12, 0)),
    Shift("01-22", time(13, 0)),
]
GRACE = timedelta(minutes=5)

def gap(a: datetime, b: datetime) -> int:
    delta = abs(a - b) - GRACE
    return max(0, int(delta.total_seconds() // 60))

def choose_shift(first_in: datetime, last_out: datetime) -> str:
    best_id, best_cost = None, float("inf")
    for s in SHIFTS:
        s_start = datetime.combine(first_in.date(), s.start)
        s_end = s_start + timedelta(hours=9)
        cost = gap(first_in, s_start) + gap(last_out, s_end)
        if cost < best_cost:
            best_id, best_cost = s.id, cost
    return best_id

def parse_attendance(attendance_str, date_str):
    if pd.isna(attendance_str) or attendance_str is None:
        return {'time_in': None, 'time_out': None, 'needs_approval': False}
    s = str(attendance_str).strip()
    n = len(s)

    def to_dt(t):
        if not t: return None
        try:
            return datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M")
        except:
            return None

    if n == 10:
        return {'time_in': to_dt(s[:5]), 'time_out': to_dt(s[5:]), 'needs_approval': False}
    if n > 10 and n % 5 == 0:
        return {'time_in': to_dt(s[:5]), 'time_out': to_dt(s[-5:]), 'needs_approval': False}
    if n == 5:
        dt = to_dt(s)
        return {'time_in': dt, 'time_out': dt, 'needs_approval': True}
    return {'time_in': None, 'time_out': None, 'needs_approval': True}

def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k,v in obj.items()}
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    if isinstance(obj, float) and (pd.isna(obj) or obj == float("inf") or obj == float("-inf")):
        return None
    if pd.isna(obj):
        return None
    return obj

# ---- UI ----
st.title("Employee Schedule Generator")

col1, col2 = st.columns(2)
with col1:
    attendance_file = st.file_uploader("Attendance report (CSV/XLS/XLSX)", type=["csv","xls","xlsx"])
with col2:
    employees_file = st.file_uploader("Employee info (optional, CSV/XLS/XLSX)", type=["csv","xls","xlsx"])

generate = st.button("Generate")

# ---------- Generate & Save Data ----------
if generate:
    if not attendance_file:
        st.error("Please upload the attendance report.")
        st.stop()

    # --- read attendance report ---
    try:
        name = attendance_file.name.lower()
        if name.endswith(".csv"):
            report = pd.read_csv(attendance_file)
        elif name.endswith(".xlsx"):
            report = pd.read_excel(attendance_file, sheet_name=2, engine="openpyxl")
        elif name.endswith(".xls"):
            report = pd.read_excel(attendance_file, sheet_name=2, engine="xlrd")
        else:
            raise ValueError("Unsupported attendance file type")
    except Exception as e:
        st.error(f"Failed to read attendance file: {e}")
        st.stop()

    # --- date range ---
    try:
        date_string = report.iloc[1, 2]
        start_date_str = date_string.split("~")[0].replace("Date:", "").strip()
        end_date_str   = date_string.split("~")[1].strip()
        date_range = pd.date_range(start=start_date_str, end=end_date_str, freq="D")
    except Exception as e:
        st.error(f"Failed to parse payroll date range: {e}")
        st.stop()

    # --- employee IDs ---
    try:
        employee_ids = report.iloc[3::2, 2].dropna().astype(str).tolist()
    except Exception as e:
        st.error(f"Failed to read employee IDs: {e}")
        st.stop()

    # --- employee names ---
    employee_names_by_id = {}
    for i, emp_id in enumerate(employee_ids):
        row_idx = 3 + (i*2)
        emp_name = None
        if row_idx < len(report) and len(report.columns) > 10:
            val = report.iloc[row_idx, 10]
            if not pd.isna(val):
                emp_name = str(val).strip()
        employee_names_by_id[emp_id] = emp_name or f"Employee {emp_id}"

    # --- init structure ---
    attendance_data = {}
    for emp_id in employee_ids:
        attendance_data[emp_id] = {
            "employee_name": employee_names_by_id.get(emp_id, f"Employee {emp_id}"),
            "dates": { d.strftime("%Y-%m-%d"): {"attendance": None, "time_in": None, "time_out": None, "needs_approval": False}
                       for d in date_range }
        }

    # --- map attendance ---
    try:
        days = report.iloc[2, 0:].dropna().tolist()
        day_to_date = {i+1: d.strftime("%Y-%m-%d") for i, d in enumerate(date_range)}
        for i, emp_id in enumerate(employee_ids):
            attendance_row = 4 + (i * 2)
            vals = report.iloc[attendance_row, 0:len(days)]
            for j, day_number in enumerate(days):
                if pd.notna(day_number) and day_number in day_to_date:
                    date_str = day_to_date[day_number]
                    attendance_data[emp_id]["dates"][date_str]["attendance"] = vals.iloc[j]
    except Exception as e:
        st.error(f"Failed to populate attendance values: {e}")
        st.stop()

    # --- parse & assign shifts ---
    for emp_id, emp in attendance_data.items():
        for date_str, rec in emp["dates"].items():
            parsed = parse_attendance(rec["attendance"], date_str)
            rec["time_in"] = parsed["time_in"]
            rec["time_out"] = parsed["time_out"]
            rec["needs_approval"] = parsed["needs_approval"]
            if rec["time_in"] and rec["time_out"] and not rec["needs_approval"]:
                rec["shift"] = choose_shift(rec["time_in"], rec["time_out"])
            else:
                rec["shift"] = None

    # --- format for UI ---
    formatted = []
    for emp_id, emp in attendance_data.items():
        employee = {
            "id": emp_id,
            "name": emp["employee_name"],
            "schedule": []
        }
        for date_str, rec in emp["dates"].items():
            employee["schedule"].append({
                "date": date_str,
                "attendance": rec.get("attendance"),
                "start": rec["time_in"].strftime("%H:%M") if rec.get("time_in") else None,
                "end":   rec["time_out"].strftime("%H:%M") if rec.get("time_out") else None,
                "shift": rec.get("shift"),
                "approval": not rec.get("needs_approval", False)
            })
        formatted.append(employee)

    st.session_state["formatted"] = clean(formatted)
    st.session_state["json_str"] = json.dumps(st.session_state["formatted"], indent=2, ensure_ascii=False)

    st.success(f"Generated schedules for {len(st.session_state['formatted'])} employees.")

# ---------- Directory & Detail Views ----------
if "formatted" in st.session_state:
    st.download_button("Download JSON",
                       data=st.session_state["json_str"],
                       file_name="employee_schedule_data.json",
                       mime="application/json")

    if "selected_emp" not in st.session_state:
        st.subheader("Employee Directory")
        search = st.text_input("Search by employee ID or name", "")

        filtered = [
            e for e in st.session_state["formatted"]
            if search.lower() in e["id"].lower() or search.lower() in e["name"].lower()
        ]

        for emp in filtered:
            col1, col2, col3 = st.columns([2,3,1])
            col1.write(emp["id"])
            col2.write(emp["name"])
            if col3.button("View schedule", key=f"view-{emp['id']}"):
                st.session_state["selected_emp"] = emp
                st.rerun()

    else:
        emp = st.session_state["selected_emp"]
        st.subheader(f"Schedule for {emp['name']} ({emp['id']})")

        df = pd.DataFrame(emp["schedule"])
        st.dataframe(df, use_container_width=True)

        if st.button("⬅ Back to list"):
            del st.session_state["selected_emp"]
            st.rerun()

