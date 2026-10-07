import frappe
from frappe import _
from frappe.model import get_permitted_fields
from frappe.model.workflow import get_workflow_name
from frappe.query_builder import Order
from frappe.utils import add_days, cint, date_diff, getdate, strip_html

from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

SUPPORTED_FIELD_TYPES = [
	"Link",
	"Select",
	"Small Text",
	"Text",
	"Long Text",
	"Text Editor",
	"Table",
	"Check",
	"Data",
	"Float",
	"Int",
	"Section Break",
	"Date",
	"Time",
	"Datetime",
	"Currency",
]


@frappe.whitelist()
def get_current_user_info() -> dict:
	current_user = frappe.session.user
	user = frappe.db.get_value(
		"User", current_user, ["name", "first_name", "full_name", "user_image"], as_dict=True
	)
	user["roles"] = frappe.get_roles(current_user)

	return user


@frappe.whitelist()
def get_current_employee_info() -> dict:
	current_user = frappe.session.user
	employee = frappe.db.get_value(
		"Employee",
		{"user_id": current_user, "status": "Active"},
		[
			"name",
			"first_name",
			"employee_name",
			"designation",
			"department",
			"company",
			"reports_to",
			"user_id",
		],
		as_dict=True,
	)
	return employee


@frappe.whitelist()
def get_all_employees() -> list[dict]:
	return frappe.get_list(
		"Employee",
		fields=[
			"name",
			"employee_name",
			"designation",
			"department",
			"company",
			"reports_to",
			"user_id",
			"image",
			"status",
		],
		limit=999999,
	)


@frappe.whitelist()
def get_reports_to_employee_name(employee: str) -> str:
	reports_to = frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "reports_to"
	)
	if not reports_to or reports_to != employee:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return frappe.db.get_value("Employee", employee, "employee_name") or ""


def get_current_employee() -> str:
	employee = get_current_employee_info().get("name")
	if not employee:
		frappe.throw(_("Employee not found"), frappe.PermissionError)
	return employee


# HR Settings
@frappe.whitelist()
def get_hr_settings() -> dict:
	settings = frappe.db.get_singles_dict("HR Settings", cast=True)
	return frappe._dict(
		allow_employee_checkin_from_mobile_app=settings.allow_employee_checkin_from_mobile_app,
		allow_geolocation_tracking=settings.allow_geolocation_tracking,
		prevent_self_leave_approval=settings.prevent_self_leave_approval,
		enable_multi_currency_expense_claim=settings.enable_multi_currency_expense_claim,
		enable_face_checkin=settings.get("enable_face_checkin"),
		require_face_checkin=settings.get("require_face_checkin"),
		face_match_threshold=settings.get("face_match_threshold") or 0.5,
		face_enroll_samples=settings.get("face_enroll_samples") or 3,
	)


# Notifications
@frappe.whitelist()
def get_unread_notifications_count() -> int:
	return frappe.db.count(
		"PWA Notification",
		{"to_user": frappe.session.user, "read": 0},
	)


@frappe.whitelist(methods=["POST"])
def mark_all_notifications_as_read() -> None:
	frappe.db.set_value(
		"PWA Notification",
		{"to_user": frappe.session.user, "read": 0},
		"read",
		1,
		update_modified=False,
	)


@frappe.whitelist()
def are_push_notifications_enabled() -> bool:
	try:
		return frappe.db.get_single_value("Push Notification Settings", "enable_push_notification_relay")
	except frappe.DoesNotExistError:
		# push notifications are not supported in the current framework version
		return False


# Attendance
@frappe.whitelist()
def get_attendance_calendar_events(from_date: str, to_date: str) -> dict:
	employee = get_current_employee()
	holidays = get_holidays_for_calendar(employee, from_date, to_date)
	attendance = get_attendance_for_calendar(employee, from_date, to_date)
	events = {}
	late_days = []
	early_exit_days = []

	date = getdate(from_date)
	while date_diff(to_date, date) >= 0:
		date_str = date.strftime("%Y-%m-%d")
		if date_str in attendance:
			record = attendance[date_str]
			events[date_str] = record["status"]
			if record.get("late_entry"):
				late_days.append(date_str)
			if record.get("early_exit"):
				early_exit_days.append(date_str)
		elif date in holidays:
			events[date_str] = "Holiday"
		date = add_days(date, 1)

	return {
		"events": events,
		"late_days": late_days,
		"early_exit_days": early_exit_days,
		"late_count": len(late_days),
		"early_exit_count": len(early_exit_days),
	}


def get_attendance_for_calendar(employee: str, from_date: str, to_date: str) -> dict[str, dict]:
	attendance = frappe.get_all(
		"Attendance",
		{"employee": employee, "attendance_date": ["between", [from_date, to_date]], "docstatus": 1},
		["attendance_date", "status", "late_entry", "early_exit"],
	)
	return {str(d["attendance_date"]): d for d in attendance}


def get_holidays_for_calendar(employee: str, from_date: str, to_date: str) -> list[str]:
	from hrms.utils.holiday_list import get_holiday_dates_between_range

	return get_holiday_dates_between_range(
		employee, from_date, to_date, raise_exception_for_holiday_list=False
	)


@frappe.whitelist()
def get_shift_requests(
	employee: str,
	approver_id: str | None = None,
	for_approval: bool = False,
	limit: int | None = None,
) -> list[dict]:
	filters = get_filters("Shift Request", employee, approver_id, for_approval)
	fields = [
		"name",
		"employee",
		"employee_name",
		"shift_type",
		"from_date",
		"to_date",
		"status",
		"approver",
		"docstatus",
		"creation",
	]

	if workflow_state_field := get_workflow_state_field("Shift Request"):
		fields.append(workflow_state_field)

	shift_requests = frappe.get_list(
		"Shift Request",
		fields=fields,
		filters=filters,
		order_by="creation desc",
		limit=limit,
	)

	if workflow_state_field:
		for application in shift_requests:
			application["workflow_state_field"] = workflow_state_field

	return shift_requests


@frappe.whitelist()
def get_attendance_requests(
	employee: str,
	for_approval: bool = False,
	limit: int | None = None,
) -> list[dict]:
	filters = get_filters("Attendance Request", employee, None, for_approval)
	fields = [
		"name",
		"reason",
		"employee",
		"employee_name",
		"from_date",
		"to_date",
		"include_holidays",
		"shift",
		"docstatus",
		"creation",
	]

	if workflow_state_field := get_workflow_state_field("Attendance Request"):
		fields.append(workflow_state_field)

	attendance_requests = frappe.get_list(
		"Attendance Request",
		fields=fields,
		filters=filters,
		order_by="creation desc",
		limit=limit,
	)

	if workflow_state_field:
		for application in attendance_requests:
			application["workflow_state_field"] = workflow_state_field

	return attendance_requests


def get_filters(
	doctype: str,
	employee: str,
	approver_id: str | None = None,
	for_approval: bool = False,
) -> dict:
	filters = frappe._dict()
	if for_approval:
		filters.docstatus = 0
		filters.employee = ("!=", employee)

		if workflow := get_workflow(doctype):
			allowed_states = get_allowed_states_for_workflow(workflow, approver_id)
			filters[workflow.workflow_state_field] = ("in", allowed_states)
		elif doctype != "Attendance Request":
			approver_field_map = {
				"Shift Request": "approver",
				"Leave Application": "leave_approver",
				"Expense Claim": "expense_approver",
			}
			filters.status = "Open" if doctype == "Leave Application" else "Draft"
			if approver_id:
				filters[approver_field_map[doctype]] = approver_id
	else:
		filters.docstatus = ("!=", 2)
		filters.employee = employee

	return filters


@frappe.whitelist()
def get_shift_request_approvers(employee: str) -> str | list[str]:
	frappe.has_permission("Employee", "read", employee, throw=True)

	shift_request_approver, department = frappe.get_cached_value(
		"Employee",
		employee,
		["shift_request_approver", "department"],
	)

	department_approvers = []
	if department:
		frappe.has_permission("Department", "read", department, throw=True)
		department_approvers = get_department_approvers(department, "shift_request_approver")
		if not shift_request_approver:
			shift_request_approver = frappe.db.get_value(
				"Department Approver",
				{"parent": department, "parentfield": "shift_request_approver", "idx": 1},
				"approver",
			)

	shift_request_approver_name = frappe.db.get_value("User", shift_request_approver, "full_name", cache=True)

	if shift_request_approver and shift_request_approver not in [
		approver.name for approver in department_approvers
	]:
		department_approvers.insert(
			0, {"name": shift_request_approver, "full_name": shift_request_approver_name}
		)

	return department_approvers


@frappe.whitelist()
def get_shifts() -> list[dict[str, str]]:
	employee = get_current_employee()
	ShiftAssignment = frappe.qb.DocType("Shift Assignment")
	ShiftType = frappe.qb.DocType("Shift Type")
	return (
		frappe.qb.from_(ShiftAssignment)
		.join(ShiftType)
		.on(ShiftAssignment.shift_type == ShiftType.name)
		.select(
			ShiftAssignment.name,
			ShiftAssignment.shift_type,
			ShiftAssignment.start_date,
			ShiftAssignment.end_date,
			ShiftType.start_time,
			ShiftType.end_time,
		)
		.where(
			(ShiftAssignment.employee == employee)
			& (ShiftAssignment.status == "Active")
			& (ShiftAssignment.docstatus == 1)
		)
		.orderby(ShiftAssignment.start_date, order=Order.asc)
	).run(as_dict=True)


# Leaves and Holidays
@frappe.whitelist()
def get_leave_applications(
	employee: str,
	approver_id: str | None = None,
	for_approval: bool = False,
	limit: int | None = None,
) -> list[dict]:
	filters = get_filters("Leave Application", employee, approver_id, for_approval)
	fields = [
		"name",
		"posting_date",
		"employee",
		"employee_name",
		"leave_type",
		"status",
		"from_date",
		"to_date",
		"half_day",
		"half_day_date",
		"description",
		"total_leave_days",
		"leave_balance",
		"leave_approver",
		"posting_date",
		"creation",
	]

	if workflow_state_field := get_workflow_state_field("Leave Application"):
		fields.append(workflow_state_field)

	applications = frappe.get_list(
		"Leave Application",
		fields=fields,
		filters=filters,
		order_by="posting_date desc",
		limit=limit,
	)

	if workflow_state_field:
		for application in applications:
			application["workflow_state_field"] = workflow_state_field

	return applications


@frappe.whitelist()
def get_leave_balance_map() -> dict[str, dict[str, float]]:
	"""
	Returns a map of leave type and balance details like:
	{
	        'Casual Leave': {'allocated_leaves': 10.0, 'balance_leaves': 5.0},
	        'Earned Leave': {'allocated_leaves': 3.0, 'balance_leaves': 3.0},
	}
	"""
	from hrms.hr.doctype.leave_application.leave_application import get_leave_details

	employee = get_current_employee()

	date = getdate()
	leave_map = {}

	leave_details = get_leave_details(employee, date)
	allocation = leave_details["leave_allocation"]

	for leave_type, details in allocation.items():
		leave_map[leave_type] = {
			"allocated_leaves": details.get("total_leaves"),
			"balance_leaves": details.get("remaining_leaves"),
		}

	return leave_map


@frappe.whitelist()
def get_leave_usage_summary(year: int | None = None) -> list[dict]:
	"""Count of leave applications per leave type for the year (excludes cancelled/rejected)."""
	from frappe.utils import flt

	employee = get_current_employee()
	year = year or getdate().year

	applications = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"from_date": ["between", [f"{year}-01-01", f"{year}-12-31"]],
			"docstatus": ["<", 2],
			"status": ["!=", "Rejected"],
		},
		fields=["leave_type", "total_leave_days"],
	)

	summary = {}
	for application in applications:
		row = summary.setdefault(
			application.leave_type,
			{"leave_type": application.leave_type, "count": 0, "days": 0.0},
		)
		row["count"] += 1
		row["days"] += flt(application.total_leave_days)

	return sorted(summary.values(), key=lambda row: row["leave_type"])


# Employee Attendance Gallery (HR back office)
EMPLOYEE_GALLERY_ROLES = ("HR Manager", "HR User", "System Manager")


def _require_employee_gallery_access() -> None:
	frappe.only_for(EMPLOYEE_GALLERY_ROLES)


def _get_accessible_employees(company: str | None = None) -> list[str]:
	filters = {}
	if company:
		filters["company"] = company
	return frappe.get_list("Employee", filters=filters, pluck="name", limit_page_length=0)


@frappe.whitelist()
def get_employee_checkin_gallery(
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	employee: str | None = None,
	log_type: str | None = None,
	face_verified: str | int | None = None,
	start: int = 0,
	page_length: int = 24,
) -> dict:
	"""Card gallery of employee check-in logs with the attendance status of that day."""
	_require_employee_gallery_access()

	to_date = getdate(to_date) if to_date else getdate()
	from_date = getdate(from_date) if from_date else to_date
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	accessible = _get_accessible_employees(company)
	if employee:
		if employee not in accessible:
			frappe.throw(_("Not permitted for employee {0}").format(employee), frappe.PermissionError)
		accessible = [employee]
	if not accessible:
		return {"rows": [], "has_more": False}

	start = cint(start) or 0
	page_length = min(cint(page_length) or 24, 100)

	filters = {
		"employee": ["in", accessible],
		"time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
	}
	if log_type in ("IN", "OUT"):
		filters["log_type"] = log_type
	if face_verified not in (None, "", "all"):
		filters["face_verified"] = cint(face_verified)

	checkins = frappe.get_all(
		"Employee Checkin",
		filters=filters,
		fields=[
			"name",
			"employee",
			"employee_name",
			"log_type",
			"time",
			"face_verified",
			"face_score",
			"face_photo",
			"latitude",
			"longitude",
		],
		order_by="time desc",
		start=start,
		page_length=page_length + 1,
	)
	has_more = len(checkins) > page_length
	checkins = checkins[:page_length]
	if not checkins:
		return {"rows": [], "has_more": False}

	employee_names = list({row.employee for row in checkins})
	employees = {
		row.name: row
		for row in frappe.get_all(
			"Employee",
			filters={"name": ["in", employee_names]},
			fields=["name", "company", "designation"],
		)
	}

	attendance_map = {}
	for row in frappe.get_all(
		"Attendance",
		filters={
			"employee": ["in", employee_names],
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=["employee", "attendance_date", "status", "late_entry", "early_exit"],
	):
		attendance_map[(row.employee, str(row.attendance_date))] = row

	for checkin in checkins:
		employee_row = employees.get(checkin.employee) or {}
		checkin["company"] = employee_row.get("company")
		checkin["designation"] = employee_row.get("designation")
		attendance = attendance_map.get((checkin.employee, str(getdate(checkin.time))))
		checkin["attendance_status"] = attendance.status if attendance else None
		checkin["late_entry"] = attendance.late_entry if attendance else 0
		checkin["early_exit"] = attendance.early_exit if attendance else 0

	return {"rows": checkins, "has_more": has_more}


@frappe.whitelist()
def get_attendance_daily_cards(employee: str, from_date: str, to_date: str) -> dict:
	"""Per-day attendance cards for one employee (drill-down of the gallery)."""
	_require_employee_gallery_access()
	frappe.has_permission("Employee", "read", employee, throw=True)

	from_date = getdate(from_date)
	to_date = getdate(to_date)

	checkins = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
		},
		fields=[
			"name",
			"log_type",
			"time",
			"face_verified",
			"face_score",
			"face_photo",
			"latitude",
			"longitude",
		],
		order_by="time asc",
		limit_page_length=0,
	)

	attendance = {
		str(row.attendance_date): row
		for row in frappe.get_all(
			"Attendance",
			filters={
				"employee": employee,
				"attendance_date": ["between", [from_date, to_date]],
				"docstatus": 1,
			},
			fields=[
				"attendance_date",
				"status",
				"late_entry",
				"early_exit",
				"in_time",
				"out_time",
				"working_hours",
			],
		)
	}

	logs_by_date = {}
	for checkin in checkins:
		logs_by_date.setdefault(str(getdate(checkin.time)), []).append(checkin)

	days = []
	date = from_date
	while date <= to_date:
		date_str = str(date)
		logs = logs_by_date.get(date_str, [])
		attendance_row = attendance.get(date_str)
		if logs or attendance_row:
			first_in = next((log for log in logs if log.log_type == "IN"), logs[0] if logs else None)
			last_out = next((log for log in reversed(logs) if log.log_type == "OUT"), None)
			days.append(
				{
					"date": date_str,
					"status": attendance_row.status if attendance_row else None,
					"late_entry": attendance_row.late_entry if attendance_row else 0,
					"early_exit": attendance_row.early_exit if attendance_row else 0,
					"first_in": first_in,
					"last_out": last_out,
					"logs": logs,
				}
			)
		date = add_days(date, 1)

	employee_info = frappe.db.get_value(
		"Employee", employee, ["employee_name", "company", "designation"], as_dict=True
	)
	return {"employee": employee_info, "days": days}


@frappe.whitelist()
def get_attendance_summary_by_employee(
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	search: str | None = None,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Per-employee attendance summary for a longer date range (weekly/monthly view)."""
	_require_employee_gallery_access()

	to_date = getdate(to_date) if to_date else getdate()
	from_date = getdate(from_date) if from_date else to_date

	filters = {"company": company} if company else {}
	if search:
		filters["employee_name"] = ["like", f"%{search}%"]

	start = cint(start) or 0
	page_length = min(cint(page_length) or 20, 100)

	employees = frappe.get_list(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "company", "designation"],
		order_by="employee_name asc",
		start=start,
		page_length=page_length + 1,
	)
	has_more = len(employees) > page_length
	employees = employees[:page_length]
	if not employees:
		return {"rows": [], "has_more": False}

	employee_names = [row.name for row in employees]
	placeholders = ", ".join(["%s"] * len(employee_names))

	attendance_counts = frappe.db.sql(
		f"""
		SELECT employee,
			SUM(CASE WHEN status IN ('Present', 'Work From Home') THEN 1 ELSE 0 END) AS present,
			SUM(CASE WHEN status = 'Half Day' THEN 1 ELSE 0 END) AS half_day,
			SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) AS absent,
			SUM(CASE WHEN status = 'On Leave' THEN 1 ELSE 0 END) AS on_leave,
			SUM(CASE WHEN late_entry = 1 THEN 1 ELSE 0 END) AS late
		FROM `tabAttendance`
		WHERE employee IN ({placeholders})
			AND attendance_date BETWEEN %s AND %s
			AND docstatus = 1
		GROUP BY employee
		""",
		employee_names + [from_date, to_date],
		as_dict=True,
	)

	log_counts = frappe.db.sql(
		f"""
		SELECT employee, COUNT(*) AS logs
		FROM `tabEmployee Checkin`
		WHERE employee IN ({placeholders})
			AND time BETWEEN %s AND %s
		GROUP BY employee
		""",
		employee_names + [f"{from_date} 00:00:00", f"{to_date} 23:59:59"],
		as_dict=True,
	)

	attendance_map = {row.employee: row for row in attendance_counts}
	log_map = {row.employee: row.logs for row in log_counts}

	rows = []
	for employee_row in employees:
		counts = attendance_map.get(employee_row.name) or {}
		rows.append(
			{
				"employee": employee_row.name,
				"employee_name": employee_row.employee_name,
				"company": employee_row.company,
				"designation": employee_row.designation,
				"present": cint(counts.get("present")),
				"half_day": cint(counts.get("half_day")),
				"absent": cint(counts.get("absent")),
				"on_leave": cint(counts.get("on_leave")),
				"late": cint(counts.get("late")),
				"logs": cint(log_map.get(employee_row.name)),
			}
		)

	return {"rows": rows, "has_more": has_more}


@frappe.whitelist()
def get_holidays_for_employee(employee: str) -> list[dict]:
	holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
	if not holiday_list:
		return []

	frappe.has_permission("Holiday List", "read", holiday_list, throw=True)

	Holiday = frappe.qb.DocType("Holiday")
	holidays = (
		frappe.qb.from_(Holiday)
		.select(Holiday.name, Holiday.holiday_date, Holiday.description)
		.where((Holiday.parent == holiday_list) & (Holiday.weekly_off == 0))
		.orderby(Holiday.holiday_date, order=Order.asc)
	).run(as_dict=True)

	for holiday in holidays:
		holiday["description"] = strip_html(holiday["description"] or "").strip()

	return holidays


@frappe.whitelist()
def get_leave_approval_details(employee: str) -> dict:
	frappe.has_permission("Employee", "read", employee, throw=True)
	leave_approver, department = frappe.get_cached_value(
		"Employee",
		employee,
		["leave_approver", "department"],
	)

	if not leave_approver and department:
		frappe.has_permission("Department", "read", department, throw=True)
		leave_approver = frappe.db.get_value(
			"Department Approver",
			{"parent": department, "parentfield": "leave_approvers", "idx": 1},
			"approver",
		)

	leave_approver_name = frappe.db.get_value("User", leave_approver, "full_name", cache=True)
	department_approvers = get_department_approvers(department, "leave_approvers")

	if leave_approver and leave_approver not in [approver.name for approver in department_approvers]:
		department_approvers.append({"name": leave_approver, "full_name": leave_approver_name})

	return dict(
		leave_approver=leave_approver,
		leave_approver_name=leave_approver_name,
		department_approvers=department_approvers,
		is_mandatory=frappe.db.get_single_value(
			"HR Settings", "leave_approver_mandatory_in_leave_application"
		),
	)


def get_department_approvers(department: str, parentfield: str) -> list[str]:
	if not department:
		return []

	department_details = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	departments = frappe.get_all(
		"Department",
		filters={
			"lft": ("<=", department_details.lft),
			"rgt": (">=", department_details.rgt),
			"disabled": 0,
		},
		pluck="name",
	)

	Approver = frappe.qb.DocType("Department Approver")
	User = frappe.qb.DocType("User")
	department_approvers = (
		frappe.qb.from_(User)
		.join(Approver)
		.on(Approver.approver == User.name)
		.select(User.name.as_("name"), User.full_name.as_("full_name"))
		.where((Approver.parent.isin(departments)) & (Approver.parentfield == parentfield))
	).run(as_dict=True)

	return department_approvers


@frappe.whitelist()
def get_leave_types(employee: str, date: str) -> list:
	from hrms.hr.doctype.leave_application.leave_application import get_leave_details

	date = date or getdate()

	# Get leave details validate leave access internally
	leave_details = get_leave_details(employee, date)
	leave_types = list(leave_details["leave_allocation"].keys()) + leave_details["lwps"]

	# include no-allocation leave types (e.g. permission/izin) that allow a
	# negative balance, so they show up even without an allocation
	no_allocation_types = frappe.get_all(
		"Leave Type",
		filters={"allow_negative": 1, "is_lwp": 0},
		pluck="name",
	)
	for leave_type in no_allocation_types:
		if leave_type not in leave_types:
			leave_types.append(leave_type)

	return leave_types


# Expense Claims
@frappe.whitelist()
def get_expense_claims(
	employee: str,
	approver_id: str | None = None,
	for_approval: bool = False,
	limit: int | None = None,
) -> list[dict]:
	filters = get_filters("Expense Claim", employee, approver_id, for_approval)
	fields = [
		"`tabExpense Claim`.name",
		"`tabExpense Claim`.posting_date",
		"`tabExpense Claim`.employee",
		"`tabExpense Claim`.employee_name",
		"`tabExpense Claim`.currency",
		"`tabExpense Claim`.approval_status",
		"`tabExpense Claim`.status",
		"`tabExpense Claim`.expense_approver",
		"`tabExpense Claim`.total_claimed_amount",
		"`tabExpense Claim`.posting_date",
		"`tabExpense Claim`.company",
		"`tabExpense Claim`.creation",
		"`tabExpense Claim Detail`.expense_type",
		{"COUNT": "`tabExpense Claim Detail`.expense_type", "as": "total_expenses"},
	]

	if workflow_state_field := get_workflow_state_field("Expense Claim"):
		fields.append(workflow_state_field)

	claims = frappe.get_list(
		"Expense Claim",
		fields=fields,
		filters=filters,
		order_by="`tabExpense Claim`.posting_date desc",
		group_by="`tabExpense Claim`.name",
		limit=limit,
	)

	if workflow_state_field:
		for claim in claims:
			claim["workflow_state_field"] = workflow_state_field

	return claims


@frappe.whitelist()
def get_expense_claim_summary() -> dict:
	employee = get_current_employee()

	from frappe.query_builder.functions import Sum

	Claim = frappe.qb.DocType("Expense Claim")

	pending_claims_case = (
		frappe.qb.terms.Case().when(Claim.approval_status == "Draft", Claim.total_claimed_amount).else_(0)
	)
	sum_pending_claims = Sum(pending_claims_case).as_("total_pending_amount")

	approved_claims_case = (
		frappe.qb.terms.Case()
		.when(Claim.approval_status == "Approved", Claim.total_sanctioned_amount)
		.else_(0)
	)
	sum_approved_claims = Sum(approved_claims_case).as_("total_approved_amount")

	approved_total_claimed_case = (
		frappe.qb.terms.Case().when(Claim.approval_status == "Approved", Claim.total_claimed_amount).else_(0)
	)
	sum_approved_total_claimed = Sum(approved_total_claimed_case).as_("total_claimed_in_approved")

	rejected_claims_case = (
		frappe.qb.terms.Case().when(Claim.approval_status == "Rejected", Claim.total_claimed_amount).else_(0)
	)
	sum_rejected_claims = Sum(rejected_claims_case).as_("total_rejected_amount")

	summary = (
		frappe.qb.from_(Claim)
		.select(
			sum_pending_claims,
			sum_approved_claims,
			sum_rejected_claims,
			sum_approved_total_claimed,
			Claim.company,
		)
		.where((Claim.docstatus != 2) & (Claim.employee == employee))
	).run(as_dict=True)[0]

	currency = frappe.db.get_value("Company", summary.company, "default_currency")
	summary["currency"] = currency

	return summary


@frappe.whitelist()
def get_expense_type_description(expense_type: str) -> str:
	return frappe.db.get_value("Expense Claim Type", expense_type, "description")


@frappe.whitelist()
def get_expense_claim_types() -> list[dict]:
	ClaimType = frappe.qb.DocType("Expense Claim Type")

	return (frappe.qb.from_(ClaimType).select(ClaimType.name, ClaimType.description)).run(as_dict=True)


@frappe.whitelist()
def get_expense_approval_details(employee: str) -> dict:
	frappe.has_permission("Employee", "read", employee, throw=True)
	expense_approver, department = frappe.get_cached_value(
		"Employee",
		employee,
		["expense_approver", "department"],
	)

	if not expense_approver and department:
		frappe.has_permission("Department", "read", department, throw=True)
		expense_approver = frappe.db.get_value(
			"Department Approver",
			{"parent": department, "parentfield": "expense_approvers", "idx": 1},
			"approver",
		)

	expense_approver_name = frappe.db.get_value("User", expense_approver, "full_name", cache=True)
	department_approvers = get_department_approvers(department, "expense_approvers")

	if expense_approver and expense_approver not in [approver.name for approver in department_approvers]:
		department_approvers.append({"name": expense_approver, "full_name": expense_approver_name})

	return dict(
		expense_approver=expense_approver,
		expense_approver_name=expense_approver_name,
		department_approvers=department_approvers,
		is_mandatory=frappe.db.get_single_value("HR Settings", "expense_approver_mandatory_in_expense_claim"),
	)


# Employee Advance
@frappe.whitelist()
def get_employee_advance_balance() -> list[dict]:
	employee = get_current_employee()
	Advance = frappe.qb.DocType("Employee Advance")

	advances = (
		frappe.qb.from_(Advance)
		.select(
			Advance.name,
			Advance.employee,
			Advance.status,
			Advance.purpose,
			Advance.paid_amount,
			(Advance.paid_amount - (Advance.claimed_amount + Advance.return_amount)).as_("balance_amount"),
			Advance.posting_date,
			Advance.currency,
		)
		.where(
			(Advance.docstatus == 1)
			& (Advance.paid_amount)
			& (Advance.employee == employee)
			# don't need claimed & returned advances, only partly or completely paid ones
			& (Advance.status.isin(["Paid", "Partially Paid", "Unpaid"]))
		)
		.orderby(Advance.posting_date, order=Order.desc)
	).run(as_dict=True)

	return advances


# Company
@frappe.whitelist()
def get_company_currencies() -> dict:
	companies = frappe.get_list("Company", fields=["name", "default_currency"])
	symbols = get_currency_symbols()
	return {
		company.name: (company.default_currency, symbols.get(company.default_currency))
		for company in companies
		if company.default_currency in symbols
	}


@frappe.whitelist()
def get_currency_symbols() -> dict:
	Currency = frappe.qb.DocType("Currency")

	currencies = (frappe.qb.from_(Currency).select(Currency.name, Currency.symbol)).run(as_dict=True)

	return {currency.name: currency.symbol or currency.name for currency in currencies}


@frappe.whitelist()
def get_company_cost_center_and_expense_account(company: str) -> dict:
	frappe.has_permission("Company", "read", company, throw=True)
	return frappe.db.get_value(
		"Company",
		company,
		["cost_center", "default_expense_claim_payable_account", "default_payroll_payable_account"],
		as_dict=True,
	)


# Form View APIs
@frappe.whitelist()
def get_doctype_fields(doctype: str) -> list[dict]:
	fields = frappe.get_meta(doctype).fields
	return [
		field
		for field in fields
		if field.fieldtype in SUPPORTED_FIELD_TYPES and field.fieldname != "amended_from"
	]


@frappe.whitelist()
def get_doctype_states(doctype: str) -> dict:
	states = frappe.get_meta(doctype).states
	return {state.title: state.color.lower() for state in states}


# File
@frappe.whitelist()
def get_attachments(dt: str, dn: str):
	frappe.has_permission(dt, "read", dn, throw=True)
	return frappe.get_list(
		"File",
		fields=["name", "file_name", "file_url", "is_private"],
		filters={"attached_to_name": str(dn), "attached_to_doctype": dt},
	)


@frappe.whitelist(methods=["POST"])
def upload_base64_file(
	content: str, filename: str, dt: str | None = None, dn: str | None = None, fieldname: str | None = None
):
	import base64
	import io
	from mimetypes import guess_type

	from PIL import Image, ImageOps

	from frappe.handler import ALLOWED_MIMETYPES

	decoded_content = base64.b64decode(content)
	content_type = guess_type(filename)[0]
	if content_type not in ALLOWED_MIMETYPES:
		frappe.throw(_("You can only upload JPG, PNG, PDF, TXT or Microsoft documents."))

	if content_type.startswith("image/jpeg"):
		# transpose the image according to the orientation tag, and remove the orientation data
		with Image.open(io.BytesIO(decoded_content)) as image:
			transpose_img = ImageOps.exif_transpose(image)
			# convert the image back to bytes
			file_content = io.BytesIO()
			transpose_img.save(file_content, format="JPEG")
			file_content = file_content.getvalue()
	else:
		file_content = decoded_content

	frappe.has_permission(dt, "write", dn, throw=True)

	return frappe.get_doc(
		{
			"doctype": "File",
			"attached_to_doctype": dt,
			"attached_to_name": dn,
			"attached_to_field": fieldname,
			"folder": "Home",
			"file_name": filename,
			"content": file_content,
			"is_private": 1,
		}
	).insert()


@frappe.whitelist(methods=["POST"])
def delete_attachment(filename: str):
	attached_to_doctype, attached_to_name = frappe.db.get_value(
		"File", filename, ["attached_to_doctype", "attached_to_name"]
	)
	if attached_to_doctype and attached_to_name:
		frappe.has_permission(attached_to_doctype, "write", attached_to_name, throw=True)
	frappe.delete_doc("File", filename)


@frappe.whitelist()
def _download_pdf(doctype: str, docname: str) -> str:
	import base64

	from frappe.utils.print_format import download_pdf

	default_print_format = frappe.get_meta(doctype).default_print_format or "Standard"

	try:
		download_pdf(doctype, docname, format=default_print_format)
	except Exception as e:
		frappe.throw(_("Failed to download PDF: {0}").format(str(e)))

	base64content = base64.b64encode(frappe.local.response.filecontent)
	content_type = frappe.local.response.type

	return f"data:{content_type};base64," + base64content.decode("utf-8")


# Workflow
@frappe.whitelist()
def get_workflow(doctype: str) -> dict:
	workflow = get_workflow_name(doctype)
	if not workflow:
		return frappe._dict()
	return frappe.get_doc("Workflow", workflow)


def get_workflow_state_field(doctype: str) -> str | None:
	workflow_name = get_workflow_name(doctype)
	if not workflow_name:
		return None

	override_status, workflow_state_field = frappe.db.get_value(
		"Workflow",
		workflow_name,
		["override_status", "workflow_state_field"],
	)
	# NOTE: checkbox labelled 'Don't Override Status' is named override_status hence the inverted logic
	if not override_status:
		return workflow_state_field
	return None


def get_allowed_states_for_workflow(workflow: dict, user_id: str) -> list[str]:
	user_roles = frappe.get_roles(user_id)
	return [transition.state for transition in workflow.transitions if transition.allowed in user_roles]


# Permissions
@frappe.whitelist()
def get_permitted_fields_for_write(doctype: str) -> list[str]:
	return get_permitted_fields(doctype, permission_type="write")
