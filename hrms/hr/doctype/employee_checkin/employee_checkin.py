# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now_datetime

from hrms.hr.doctype.shift_assignment.shift_assignment import get_actual_start_end_datetime_of_shift
from hrms.hr.utils import (
	get_distance_between_coordinates,
	set_geolocation_from_coordinates,
	validate_active_employee,
)

# users with any of these roles bypass the self-service checkin restrictions
SELF_SERVICE_BYPASS_ROLES = {"HR Manager", "HR User", "System Manager"}
# allowed clock drift between server time and the submitted log time (in seconds)
SELF_CHECKIN_TIME_TOLERANCE_SECONDS = 900


class CheckinRadiusExceededError(frappe.ValidationError):
	pass


class EmployeeCheckin(Document):
	def before_validate(self):
		self.time = get_datetime(self.time).replace(microsecond=0)

	def validate(self):
		validate_active_employee(self.employee)
		self.validate_duplicate_log()
		self.validate_time_change()
		self.fetch_shift()
		self.set_geolocation()
		self.validate_distance_from_shift_location()
		self.validate_self_service_checkin()

	def validate_duplicate_log(self):
		doc = frappe.db.exists(
			"Employee Checkin",
			{
				"employee": self.employee,
				"time": self.time,
				"name": ("!=", self.name),
				"log_type": self.log_type,
			},
		)
		if doc:
			doc_link = frappe.get_desk_link("Employee Checkin", doc)
			frappe.throw(
				_("This employee already has a log with the same timestamp.{0}").format("<Br>" + doc_link)
			)

	def validate_time_change(self):
		if self.attendance and self.has_value_changed("time"):
			frappe.throw(
				title=_("Cannot Modify Time"),
				msg=_(
					"An attendance record is linked to this checkin. Please cancel the attendance before modifying time."
				),
			)

	@frappe.whitelist()
	def set_geolocation(self):
		set_geolocation_from_coordinates(self)

	@frappe.whitelist()
	def fetch_shift(self):
		if not (
			shift_actual_timings := get_actual_start_end_datetime_of_shift(
				self.employee, get_datetime(self.time), True
			)
		):
			self.shift = None
			self.offshift = 1
			return

		if (
			shift_actual_timings.shift_type.determine_check_in_and_check_out
			== "Strictly based on Log Type in Employee Checkin"
			and not self.log_type
			and not self.skip_auto_attendance
		):
			frappe.throw(
				_("Log Type is required for check-ins falling in the shift: {0}.").format(
					shift_actual_timings.shift_type.name
				)
			)
		if not self.attendance:
			self.offshift = 0
			self.shift = shift_actual_timings.shift_type.name
			self.shift_actual_start = shift_actual_timings.actual_start
			self.shift_actual_end = shift_actual_timings.actual_end
			self.shift_start = shift_actual_timings.start_datetime
			self.shift_end = shift_actual_timings.end_datetime
			self.overtime_type = shift_actual_timings.overtime_type or None

	def validate_distance_from_shift_location(self):
		if not frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"):
			return

		if not (self.latitude or self.longitude):
			frappe.throw(_("Latitude and longitude values are required for checking in."))

		assignment_locations = frappe.get_all(
			"Shift Assignment",
			filters={
				"employee": self.employee,
				"shift_type": self.shift,
				"start_date": ["<=", self.time],
				"shift_location": ["is", "set"],
				"docstatus": 1,
				"status": "Active",
			},
			or_filters=[["end_date", ">=", self.time], ["end_date", "is", "not set"]],
			pluck="shift_location",
		)
		if not assignment_locations:
			return

		checkin_radius, latitude, longitude = frappe.db.get_value(
			"Shift Location", assignment_locations[0], ["checkin_radius", "latitude", "longitude"]
		)
		if checkin_radius <= 0:
			return

		distance = get_distance_between_coordinates(latitude, longitude, self.latitude, self.longitude)
		if distance > checkin_radius:
			frappe.throw(
				_("You must be within {0} meters of your shift location to check in.").format(checkin_radius),
				exc=CheckinRadiusExceededError,
			)

	def validate_self_service_checkin(self):
		"""Restrict employee self-service check-ins:
		- no backdated/future logs (time must be close to server time)
		- face verification required when configured
		- check-out only allowed when there is an open check-in within the allowed window
		"""
		if not self.is_new() or self.flags.get("ignore_checkin_restrictions"):
			return

		if frappe.session.user == "Administrator" or set(frappe.get_roles()) & SELF_SERVICE_BYPASS_ROLES:
			return

		self.validate_self_service_time()
		self.validate_daily_checkin_limit()
		self.validate_face_verification()
		self.validate_checkout_window()

	def validate_daily_checkin_limit(self):
		"""Allow only one check-in per day (and one check-out via the open check-in rule)."""
		if self.log_type != "IN":
			return

		day_start = get_datetime(self.time).replace(hour=0, minute=0, second=0, microsecond=0)
		day_end = day_start + timedelta(days=1)
		if frappe.db.exists(
			"Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "IN",
				"time": ["between", [day_start, day_end]],
				"name": ("!=", self.name),
			},
		):
			frappe.throw(
				title=_("Already Checked In"),
				msg=_("You have already checked in today. Please check out instead."),
			)

	def validate_self_service_time(self):
		drift = abs((get_datetime(self.time) - now_datetime()).total_seconds())
		if drift > SELF_CHECKIN_TIME_TOLERANCE_SECONDS:
			frappe.throw(
				title=_("Invalid Check-in Time"),
				msg=_(
					"You cannot check in or out for a past or future time. "
					"Please raise an Attendance Request to regularize your attendance."
				),
			)

	def validate_face_verification(self):
		if not frappe.db.get_single_value("HR Settings", "require_face_checkin"):
			return

		if not self.face_verified:
			frappe.throw(
				title=_("Face Verification Required"),
				msg=_("Please verify your face in the mobile app to check in or out."),
			)

	def validate_checkout_window(self):
		if self.log_type != "OUT":
			return

		last_log = frappe.get_all(
			"Employee Checkin",
			filters={"employee": self.employee, "name": ("!=", self.name)},
			fields=["name", "log_type", "time", "shift_actual_end"],
			order_by="time desc",
			limit=1,
		)
		if not last_log or last_log[0].log_type != "IN":
			frappe.throw(_("No open check-in found. Please check in before checking out."))

		cutoff = get_checkout_cutoff(last_log[0])
		if get_datetime(self.time) > cutoff:
			frappe.throw(
				title=_("Check-out Window Expired"),
				msg=_(
					"Checking out for a previous day is not allowed. "
					"Please raise an Attendance Request to regularize your attendance."
				),
			)

	def after_insert(self):
		self.queue_realtime_attendance()

	def queue_realtime_attendance(self):
		"""Mark attendance as soon as a check-out completes the day's pair.

		Standard HRMS only finalises attendance after the shift ends via the
		hourly job, so a same-day check-in/out stays invisible to the employee
		calendar and HR until then.
		"""
		if self.log_type != "OUT" or not self.shift or cint(self.skip_auto_attendance):
			return
		frappe.enqueue(
			"hrms.hr.doctype.employee_checkin.employee_checkin.process_shift_attendance_now",
			queue="short",
			enqueue_after_commit=True,
			shift=self.shift,
			employee=self.employee,
		)


def process_shift_attendance_now(shift: str, employee: str) -> None:
	"""Process auto attendance for one employee's shift without waiting for shift end.

	Called right after a check-out; only runs when the check-in of the pair is
	still unmarked, and pulls `last_sync_of_checkin` forward so the standard
	shift-type processor picks the logs up.
	"""
	pending_in = frappe.db.exists(
		"Employee Checkin",
		{"employee": employee, "shift": shift, "log_type": "IN", "attendance": ("is", "not set")},
	)
	if not pending_in:
		return

	# jobs run as the enqueuing user (the employee); attendance marking needs HR rights
	frappe.set_user("Administrator")

	shift_doc = frappe.get_doc("Shift Type", shift)
	if not cint(shift_doc.enable_auto_attendance):
		return

	last_log = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "shift": shift, "attendance": ("is", "not set")},
		fields=["shift_actual_end"],
		order_by="shift_actual_end desc",
		limit=1,
	)
	if last_log and last_log[0].shift_actual_end:
		last_sync = get_datetime(last_log[0].shift_actual_end) + timedelta(minutes=1)
		frappe.db.set_value("Shift Type", shift, "last_sync_of_checkin", last_sync)
		shift_doc.last_sync_of_checkin = last_sync

	shift_doc.process_auto_attendance()


def get_checkout_cutoff(open_checkin) -> datetime:
	"""Check-out is allowed until the end of the day the shift (or check-in) belongs to."""
	reference_time = open_checkin.get("shift_actual_end") or open_checkin.get("time")
	return get_datetime(reference_time).replace(hour=23, minute=59, second=59, microsecond=0)


@frappe.whitelist(methods=["POST"])
def add_log_based_on_employee_field(
	employee_field_value: str | int,
	timestamp: str | datetime,
	device_id: str | int | None = None,
	log_type: str | None = None,
	skip_auto_attendance: str | bool | int = 0,
	employee_fieldname: str = "attendance_device_id",
	latitude: str | float | None = None,
	longitude: str | float | None = None,
) -> Document:
	"""Finds the relevant Employee using the employee field value and creates a Employee Checkin.

	:param employee_field_value: The value to look for in employee field.
	:param timestamp: The timestamp of the Log. Currently expected in the following format as string: '2019-05-08 10:48:08.000000'
	:param device_id: (optional)Location / Device ID. A short string is expected.
	:param log_type: (optional)Direction of the Punch if available (IN/OUT).
	:param skip_auto_attendance: (optional)Skip auto attendance field will be set for this log(0/1).
	:param employee_fieldname: (Default: attendance_device_id)Name of the field in Employee DocType based on which employee lookup will happen.
	:latitude: (optional) Latitude of the shift location.
	:longitude: (optional) Longitude of the shift location.
	"""

	if not employee_field_value or not timestamp:
		frappe.throw(_("'employee_field_value' and 'timestamp' are required."))

	allowed_employee_fieldnames = {"name", "employee", "attendance_device_id"}
	if employee_fieldname not in allowed_employee_fieldnames:
		frappe.throw(
			_("'employee_fieldname' must be one of {0}.").format(", ".join(allowed_employee_fieldnames))
		)

	employee = frappe.db.get_values(
		"Employee",
		{employee_fieldname: employee_field_value},
		["name", "employee_name", employee_fieldname],
		as_dict=True,
	)
	if employee:
		employee = employee[0]
	else:
		frappe.throw(
			_("No Employee found for the given employee field value. '{}': {}").format(
				employee_fieldname, employee_field_value
			)
		)

	doc = frappe.new_doc("Employee Checkin")
	doc.employee = employee.name
	doc.employee_name = employee.employee_name
	doc.time = timestamp
	doc.device_id = device_id
	doc.log_type = log_type
	doc.latitude = latitude
	doc.longitude = longitude
	if cint(skip_auto_attendance) == 1:
		doc.skip_auto_attendance = "1"
	# logs pushed from external devices may legitimately be backdated
	doc.flags.ignore_checkin_restrictions = True
	doc.insert()

	return doc


@frappe.whitelist(methods=["POST"])
def bulk_fetch_shift(checkins: list[str] | str) -> None:
	if isinstance(checkins, str):
		checkins = frappe.json.loads(checkins)
	for d in checkins:
		doc = frappe.get_doc("Employee Checkin", d)
		doc.fetch_shift()
		doc.flags.ignore_validate = True
		doc.save()


def mark_attendance_and_link_log(
	logs: list[Document],
	attendance_status: str,
	attendance_date: str | date,
	working_hours: float | None = None,
	late_entry: int | bool = False,
	early_exit: int | bool = False,
	in_time: datetime | None = None,
	out_time: datetime | None = None,
	shift: str | None = None,
	overtime_type: str | None = None,
) -> Document | None:
	"""Creates an attendance and links the attendance to the Employee Checkin.
	Note: If attendance is already present for the given date, the logs are marked as skipped and no exception is thrown.

	:param logs: The List of 'Employee Checkin'.
	:param attendance_status: Attendance status to be marked. One of: (Present, Absent, Half Day, Skip). Note: 'On Leave' is not supported by this function.
	:param attendance_date: Date of the attendance to be created.
	:param working_hours: (optional)Number of working hours for the given date.
	"""
	log_names = [x.name for x in logs]
	employee = logs[0].employee

	if attendance_status == "Skip":
		skip_attendance_in_checkins(log_names)
		return None

	if attendance_status not in ("Present", "Absent", "Half Day"):
		frappe.throw(_("{0} is an invalid Attendance Status.").format(attendance_status))

	try:
		frappe.db.savepoint("attendance_creation")

		attendance = create_or_update_attendance(
			employee=employee,
			attendance_date=attendance_date,
			attendance_status=attendance_status,
			working_hours=working_hours,
			shift=shift,
			late_entry=late_entry,
			early_exit=early_exit,
			in_time=in_time,
			out_time=out_time,
			overtime_type=overtime_type,
		)

		if attendance_status == "Absent":
			attendance.add_comment(
				text=_("Employee was marked Absent for not meeting the working hours threshold.")
			)

		update_attendance_in_checkins(log_names, attendance.name)
		return attendance

	except frappe.ValidationError as e:
		handle_attendance_exception(log_names, e)
		return None


def create_or_update_attendance(
	employee,
	attendance_date,
	attendance_status,
	working_hours=None,
	shift=None,
	late_entry=False,
	early_exit=False,
	in_time=None,
	out_time=None,
	overtime_type=None,
):
	"""Creates a new attendance or updates an existing half-day attendance."""
	if attendance := get_existing_half_day_attendance(employee, attendance_date):
		frappe.db.set_value(
			"Attendance",
			attendance.name,
			{
				"working_hours": working_hours,
				"shift": shift,
				"late_entry": late_entry,
				"early_exit": early_exit,
				"in_time": in_time,
				"out_time": out_time,
				"half_day_status": "Absent" if attendance_status == "Absent" else "Present",
				"modify_half_day_status": 0,
			},
		)
		return frappe.get_doc("Attendance", attendance.name)
	else:
		attendance = frappe.new_doc("Attendance")
		attendance.update(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": attendance_date,
				"status": attendance_status,
				"working_hours": working_hours,
				"shift": shift,
				"late_entry": late_entry,
				"early_exit": early_exit,
				"in_time": in_time,
				"out_time": out_time,
			}
		)

		# Set overtime data if applicable
		if overtime_type and attendance_status == "Present":
			overtime_data = get_overtime_data(shift, working_hours)
			if overtime_data:
				attendance.update(
					{
						"overtime_type": overtime_type,
						"standard_working_hours": overtime_data.get("standard_working_hours"),
						"actual_overtime_duration": overtime_data.get("actual_overtime_duration"),
					}
				)
		attendance.save()
		attendance.submit()

	return attendance


def get_overtime_data(shift_name, working_hours):
	overtime_data = {}

	shift_type_details = frappe.db.get_value(
		doctype="Shift Type",
		filters={"name": shift_name},
		fieldname=["allow_overtime", "start_time", "end_time"],
		as_dict=True,
	)

	if not shift_type_details or not shift_type_details.allow_overtime:
		return overtime_data

	standard_working_hours = calculate_time_difference(
		shift_type_details.start_time, shift_type_details.end_time
	)

	if working_hours > standard_working_hours:
		actual_overtime_duration = working_hours - standard_working_hours
		overtime_data = {
			"standard_working_hours": standard_working_hours,
			"actual_overtime_duration": actual_overtime_duration,
		}

	return overtime_data


def get_existing_half_day_attendance(employee, attendance_date):
	attendance_name = frappe.db.exists(
		"Attendance",
		{
			"employee": employee,
			"attendance_date": attendance_date,
			"status": "Half Day",
			"modify_half_day_status": 1,
			"leave_type": ("is", "set"),
		},
	)

	if attendance_name:
		attendance_doc = frappe.get_doc("Attendance", attendance_name)
		return attendance_doc
	return None


def calculate_working_hours(logs, check_in_out_type, working_hours_calc_type):
	"""Given a set of logs in chronological order calculates the total working hours based on the parameters.
	Zero is returned for all invalid cases.

	:param logs: The List of 'Employee Checkin'.
	:param check_in_out_type: One of: 'Alternating entries as IN and OUT during the same shift', 'Strictly based on Log Type in Employee Checkin'
	:param working_hours_calc_type: One of: 'First Check-in and Last Check-out', 'Every Valid Check-in and Check-out'
	"""
	total_hours = 0
	in_time = out_time = None
	if check_in_out_type == "Alternating entries as IN and OUT during the same shift":
		in_time = logs[0].time
		if len(logs) >= 2:
			out_time = logs[-1].time
		if working_hours_calc_type == "First Check-in and Last Check-out":
			# assumption in this case: First log always taken as IN, Last log always taken as OUT
			total_hours = time_diff_in_hours(in_time, logs[-1].time)
		elif working_hours_calc_type == "Every Valid Check-in and Check-out":
			logs = logs[:]
			while len(logs) >= 2:
				total_hours += time_diff_in_hours(logs[0].time, logs[1].time)
				del logs[:2]

	elif check_in_out_type == "Strictly based on Log Type in Employee Checkin":
		if working_hours_calc_type == "First Check-in and Last Check-out":
			first_in_log_index = find_index_in_dict(logs, "log_type", "IN")
			first_in_log = logs[first_in_log_index] if first_in_log_index or first_in_log_index == 0 else None
			last_out_log_index = find_index_in_dict(reversed(logs), "log_type", "OUT")
			last_out_log = (
				logs[len(logs) - 1 - last_out_log_index]
				if last_out_log_index or last_out_log_index == 0
				else None
			)
			in_time = getattr(first_in_log, "time", None)
			out_time = getattr(last_out_log, "time", None)
			if first_in_log and last_out_log:
				total_hours = time_diff_in_hours(in_time, out_time)
		elif working_hours_calc_type == "Every Valid Check-in and Check-out":
			in_log = out_log = None
			for log in logs:
				if in_log and out_log:
					if not in_time:
						in_time = in_log.time
					out_time = out_log.time
					total_hours += time_diff_in_hours(in_log.time, out_log.time)
					in_log = out_log = None
				if not in_log:
					in_log = log if log.log_type == "IN" else None
					if in_log and not in_time:
						in_time = in_log.time
				elif not out_log:
					out_log = log if log.log_type == "OUT" else None

			if in_log and out_log:
				out_time = out_log.time
				total_hours += time_diff_in_hours(in_log.time, out_log.time)

	return total_hours, in_time, out_time


def time_diff_in_hours(start, end):
	return round(float((end - start).total_seconds()) / 3600, 2)


def find_index_in_dict(dict_list, key, value):
	return next((index for (index, d) in enumerate(dict_list) if d[key] == value), None)


def handle_attendance_exception(log_names: list, error_message: str):
	frappe.db.rollback(save_point="attendance_creation")
	frappe.clear_messages()
	skip_attendance_in_checkins(log_names)
	add_comment_in_checkins(log_names, error_message)


def add_comment_in_checkins(log_names: list, error_message: str):
	text = "{prefix}<br>{error_message}".format(
		prefix=frappe.bold(_("Reason for skipping auto attendance:")), error_message=error_message
	)

	for name in log_names:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Employee Checkin",
				"reference_name": name,
				"content": text,
			}
		).insert(ignore_permissions=True)


def skip_attendance_in_checkins(log_names: list):
	EmployeeCheckin = frappe.qb.DocType("Employee Checkin")
	(
		frappe.qb.update(EmployeeCheckin)
		.set("skip_auto_attendance", 1)
		.where(EmployeeCheckin.name.isin(log_names))
	).run()


def update_attendance_in_checkins(log_names: list, attendance_id: str):
	EmployeeCheckin = frappe.qb.DocType("Employee Checkin")
	(
		frappe.qb.update(EmployeeCheckin)
		.set("attendance", attendance_id)
		.where(EmployeeCheckin.name.isin(log_names))
	).run()


def calculate_time_difference(start_time, end_time):
	if end_time < start_time:
		end_time += timedelta(days=1)
	time_difference = abs(start_time - end_time)

	return round(time_difference.total_seconds() / 3600, 2)
