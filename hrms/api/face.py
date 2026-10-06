# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from hrms.api import get_current_employee
from hrms.hr.doctype.employee_face_profile.employee_face_profile import FACE_DESCRIPTOR_LENGTH
from hrms.hr.utils import validate_active_employee

HR_ROLES = ("HR Manager", "HR User", "System Manager")
DEFAULT_MATCH_THRESHOLD = 0.5


def _get_optional_current_employee() -> str | None:
	return frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
	)


def _resolve_employee(employee: str | None = None) -> str:
	"""Return the employee being acted upon. Non-HR users may only act on themselves."""
	if employee:
		if employee != _get_optional_current_employee():
			frappe.only_for(HR_ROLES)
		return employee
	return get_current_employee()


def _validate_descriptor(descriptor: str | list) -> list[float]:
	if isinstance(descriptor, str):
		try:
			descriptor = json.loads(descriptor)
		except ValueError:
			frappe.throw(_("Invalid face descriptor."))

	if not isinstance(descriptor, (list, tuple)) or len(descriptor) != FACE_DESCRIPTOR_LENGTH:
		frappe.throw(_("Invalid face descriptor."))

	return [float(value) for value in descriptor]


def _euclidean_distance(first: list[float], second: list[float]) -> float:
	return sum((a - b) ** 2 for a, b in zip(first, second)) ** 0.5


def _save_photo_data_url(
	data_url: str, attached_to_doctype: str, attached_to_name: str, filename: str
) -> str | None:
	if not data_url or ";base64," not in data_url:
		return None

	header, encoded = data_url.split(";base64,", 1)
	extension = "png" if "png" in header else "jpg"
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{filename}.{extension}",
			"attached_to_doctype": attached_to_doctype,
			"attached_to_name": attached_to_name,
			"is_private": 1,
			"content": encoded,
			"decode": True,
		}
	)
	file_doc.flags.ignore_permissions = True
	file_doc.insert()
	return file_doc.file_url


@frappe.whitelist()
def get_face_status(employee: str | None = None) -> dict:
	employee = _resolve_employee(employee)
	profile = frappe.db.get_value(
		"Employee Face Profile",
		{"employee": employee, "status": "Enrolled"},
		["name", "enrolled_on"],
		as_dict=True,
	)
	return {
		"employee": employee,
		"enrolled": bool(profile),
		"profile": profile.name if profile else None,
		"enrolled_on": profile.enrolled_on if profile else None,
	}


@frappe.whitelist(methods=["POST"])
def enroll_face(
	descriptors: str | list, photo: str | None = None, employee: str | None = None
) -> dict:
	employee = _resolve_employee(employee)
	validate_active_employee(employee)

	samples = json.loads(descriptors) if isinstance(descriptors, str) else descriptors
	if not samples:
		frappe.throw(_("At least one face sample is required for enrollment."))

	samples = [_validate_descriptor(sample) for sample in samples]
	average_descriptor = [sum(values) / len(values) for values in zip(*samples)]

	profile_name = frappe.db.get_value("Employee Face Profile", {"employee": employee})
	doc = (
		frappe.get_doc("Employee Face Profile", profile_name)
		if profile_name
		else frappe.new_doc("Employee Face Profile")
	)
	doc.employee = employee
	doc.status = "Enrolled"
	doc.descriptor = json.dumps(average_descriptor)
	doc.enrolled_on = now_datetime()
	doc.enrolled_by = frappe.session.user
	doc.flags.ignore_permissions = True
	doc.save()

	if photo:
		photo_url = _save_photo_data_url(
			photo, "Employee Face Profile", doc.name, f"face-{doc.name}"
		)
		if photo_url:
			frappe.db.set_value(
				"Employee Face Profile", doc.name, "photo", photo_url, update_modified=False
			)

	frappe.db.commit()
	return {"profile": doc.name, "enrolled": True, "samples": len(samples)}


@frappe.whitelist(methods=["POST"])
def reset_face(employee: str) -> dict:
	frappe.only_for(HR_ROLES)
	profile_name = frappe.db.get_value("Employee Face Profile", {"employee": employee})
	if not profile_name:
		return {"reset": False}

	frappe.delete_doc("Employee Face Profile", profile_name, ignore_permissions=True)
	frappe.db.commit()
	return {"reset": True}


@frappe.whitelist(methods=["POST"])
def face_checkin(
	log_type: str,
	descriptor: str | list,
	latitude: float | str | None = None,
	longitude: float | str | None = None,
	photo: str | None = None,
) -> dict:
	employee = get_current_employee()
	log_type = (log_type or "").upper()
	if log_type not in ("IN", "OUT"):
		frappe.throw(_("Log Type must be either IN or OUT."))

	validate_active_employee(employee)
	descriptor = _validate_descriptor(descriptor)

	profile = frappe.db.get_value(
		"Employee Face Profile",
		{"employee": employee, "status": "Enrolled"},
		["name", "descriptor"],
		as_dict=True,
	)
	if not profile:
		frappe.throw(_("No enrolled face found. Please enroll your face first."))

	threshold = (
		flt(frappe.db.get_single_value("HR Settings", "face_match_threshold"))
		or DEFAULT_MATCH_THRESHOLD
	)
	score = _euclidean_distance(descriptor, json.loads(profile.descriptor))
	if score > threshold:
		frappe.throw(
			title=_("Face Verification Failed"),
			msg=_("Face verification failed (match score {0}, allowed {1}). Please try again.").format(
				round(score, 4), threshold
			),
		)

	checkin = frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"employee": employee,
			"log_type": log_type,
			"time": now_datetime(),
			"latitude": latitude or None,
			"longitude": longitude or None,
			"face_verified": 1,
			"face_score": round(score, 4),
		}
	)
	checkin.insert()

	if photo:
		photo_url = _save_photo_data_url(
			photo, "Employee Checkin", checkin.name, f"checkin-{checkin.name}"
		)
		if photo_url:
			frappe.db.set_value(
				"Employee Checkin", checkin.name, "face_photo", photo_url, update_modified=False
			)

	frappe.db.commit()
	return {
		"name": checkin.name,
		"log_type": checkin.log_type,
		"time": checkin.time,
		"face_score": checkin.face_score,
	}
