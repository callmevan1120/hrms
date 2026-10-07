import "./templates/employees_with_unmarked_attendance.html";
import "./templates/feedback_summary.html";
import "./templates/feedback_history.html";
import "./templates/rating.html";
import "./utils";
import "./utils/payroll_utils";
import "./utils/leave_utils";
import "./utils/telemetry.js";
import "./salary_slip_deductions_report_filters.js";

// Frappe desk caches standard pages in localStorage, which keeps stale page
// scripts/styles after an update. Drop the cached attendance gallery page on
// every desk boot so it always loads the current version from the app.
try {
	localStorage.removeItem("_page:employee-attendance-gallery");
} catch (e) {
	// ignore storage errors (private mode etc.)
}
