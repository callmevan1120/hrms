import frappe
from frappe.boot import load_translations

no_cache = 1


def get_context(context):
	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()  # nosempgrep
	context = frappe._dict()
	context.csrf_token = csrf_token
	context.boot = get_boot()
	context.site_name = frappe.local.site
	return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	if not frappe.conf.developer_mode:
		frappe.throw(frappe._("This method is only meant for developer mode"))
	return get_boot()


def get_boot():
	bootinfo = frappe._dict(
		{
			"site_name": frappe.local.site,
			"socketio_port": frappe.conf.get("socketio_port") or 9000,
			"push_relay_server_url": frappe.conf.get("push_relay_server_url") or "",
			"default_route": get_default_route(),
		}
	)

	# resolve language from the user / system settings (not the browser accept-language)
	# so the app language stays consistent between nav and content
	frappe.local.lang = get_user_language()
	load_translations(bootinfo)

	return bootinfo


def get_user_language():
	lang = None
	if frappe.session.user and frappe.session.user != "Guest":
		lang = frappe.db.get_value("User", frappe.session.user, "language")

	return lang or frappe.db.get_single_value("System Settings", "language") or "en"


def get_default_route():
	return "/hrms"
