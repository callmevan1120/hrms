# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json

import frappe
from frappe import _
from frappe.model.document import Document

FACE_DESCRIPTOR_LENGTH = 128


class EmployeeFaceProfile(Document):
	def validate(self):
		self.validate_descriptor()

	def validate_descriptor(self):
		if not self.descriptor:
			frappe.throw(_("Face descriptor is required for enrollment."))

		try:
			descriptor = json.loads(self.descriptor)
		except (TypeError, ValueError):
			frappe.throw(_("Invalid face descriptor."))

		if not isinstance(descriptor, list) or len(descriptor) != FACE_DESCRIPTOR_LENGTH:
			frappe.throw(
				_("Face descriptor must contain {0} values.").format(FACE_DESCRIPTOR_LENGTH)
			)

		self.descriptor = json.dumps([float(value) for value in descriptor])
