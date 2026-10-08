frappe.pages["employee-attendance-gallery"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Employee Attendance Gallery"),
		single_column: true,
	});

	frappe.employee_attendance_gallery = new EmployeeAttendanceGallery(page);
};

frappe.pages["employee-attendance-gallery"].on_page_show = function () {
	// page is kept alive in the desk, data is refreshed via the Refresh button
};

class EmployeeAttendanceGallery {
	constructor(page) {
		this.page = page;
		this.page.main.addClass("eag-page");
		this.mode = "auto";
		this.view = "main";
		this.selected_employee = null;
		this.start = 0;
		this.page_length = 24;
		this.request_id = 0;
		this.current_rows = [];
		this.search_value = "";

		this.setup_dates("Today");
		this.make_filters();
		this.make_container();
		this.make_tweaks();
		this.update_mode_buttons();
		this.refresh();
	}

	/* ------------------------------- filters ------------------------------- */

	setup_dates(preset) {
		const today = frappe.datetime.get_today();
		if (preset === "Yesterday") {
			this.from_date = frappe.datetime.add_days(today, -1);
			this.to_date = this.from_date;
		} else if (preset === "Last 7 Days") {
			this.from_date = frappe.datetime.add_days(today, -6);
			this.to_date = today;
		} else if (preset === "Last 30 Days") {
			this.from_date = frappe.datetime.add_days(today, -29);
			this.to_date = today;
		} else if (preset === "Today") {
			this.from_date = today;
			this.to_date = today;
		}
	}

	make_filters() {
		this.$filters = $('<div class="eag-filters"></div>').appendTo(this.page.main);

		const add_filter = (label, $control) => {
			const $field = $(
				`<div class="eag-filter"><div class="eag-filter-label">${frappe.utils.escape_html(
					label
				)}</div></div>`
			);
			$field.append($control).appendTo(this.$filters);
			return $field;
		};

		// company
		this.$company = $(
			`<select class="form-control eag-input eag-company"><option value="">${__(
				"All Companies"
			)}</option></select>`
		);
		frappe.db
			.get_list("Company", { fields: ["name"], limit_page_length: 0, order_by: "name" })
			.then((companies) => {
				const options = (companies || []).map(
					(company) =>
						`<option value="${frappe.utils.escape_html(company.name)}">${frappe.utils.escape_html(
							company.name
						)}</option>`
				);
				this.$company.append(options.join(""));
			});
		add_filter(__("Company"), this.$company);
		this.$company.on("change", () => this.refresh());

		// period: preset + date range under one label
		this.$preset = $(`
			<select class="form-control eag-input eag-preset">
				<option value="Today">${__("Today")}</option>
				<option value="Yesterday">${__("Yesterday")}</option>
				<option value="Last 7 Days">${__("Last 7 Days")}</option>
				<option value="Last 30 Days">${__("Last 30 Days")}</option>
				<option value="Custom">${__("Custom")}</option>
			</select>
		`);
		this.$from = $('<input type="date" class="form-control eag-input eag-date">');
		this.$to = $('<input type="date" class="form-control eag-input eag-date">');
		const $period_row = $('<div class="eag-period-row"></div>')
			.append(this.$preset)
			.append(this.$from)
			.append('<span class="eag-dash">–</span>')
			.append(this.$to);
		add_filter(__("Period"), $period_row);
		this.render_dates();

		this.$preset.on("change", () => {
			this.setup_dates(this.$preset.val());
			this.render_dates();
			this.refresh();
		});
		this.$from.on("change", () => {
			this.$preset.val("Custom");
			this.refresh();
		});
		this.$to.on("change", () => {
			this.$preset.val("Custom");
			this.refresh();
		});

		// search (applies to both gallery and per-employee view)
		this.$search = $(
			`<input type="text" class="form-control eag-input eag-search" placeholder="${__(
				"Search employee"
			)}" value="${frappe.utils.escape_html(this.search_value)}">`
		);
		add_filter(__("Search"), this.$search);
		this.$search.on(
			"input",
			frappe.utils.debounce(() => {
				this.search_value = this.$search.val();
				if (this.view === "main") this.refresh();
			}, 450)
		);

		// log type
		this.$log_type = $(`
			<select class="form-control eag-input eag-narrow">
				<option value="">${__("All")}</option>
				<option value="IN">IN</option>
				<option value="OUT">OUT</option>
			</select>
		`);
		add_filter(__("Log Type"), this.$log_type);
		this.$log_type.on("change", () => this.refresh());

		// face verified
		this.$face = $(`
			<select class="form-control eag-input eag-narrow">
				<option value="">${__("All")}</option>
				<option value="1">${__("Verified")}</option>
				<option value="0">${__("Unverified")}</option>
			</select>
		`);
		add_filter(__("Face Verified"), this.$face);
		this.$face.on("change", () => this.refresh());

		// view mode + refresh, last group, pushed to the right of the same row
		const $actions = $('<div class="eag-filter eag-actions"></div>').append(
			'<div class="eag-filter-label">&nbsp;</div>'
		);
		$actions.appendTo(this.$filters);
		const $actions_row = $('<div class="eag-actions-row"></div>').appendTo($actions);

		this.$mode = $(`
			<div class="eag-seg" role="group" aria-label="${__("View Mode")}">
				<button type="button" data-mode="auto">${__("Auto")}</button>
				<button type="button" data-mode="gallery">${__("Gallery")}</button>
				<button type="button" data-mode="list">${__("Per Employee")}</button>
			</div>
		`).appendTo($actions_row);
		this.$mode.on("click", "button", (event) => {
			this.mode = $(event.currentTarget).attr("data-mode");
			this.update_mode_buttons();
			this.refresh();
		});

		$(
			`<button type="button" class="btn btn-default eag-refresh" title="${__("Refresh")}">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
					stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<polyline points="23 4 23 10 17 10"></polyline>
					<polyline points="1 20 1 14 7 14"></polyline>
					<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
				</svg>
			</button>`
		)
			.appendTo($actions_row)
			.on("click", () => this.refresh());
	}

	render_dates() {
		this.$from.val(this.from_date);
		this.$to.val(this.to_date);
	}

	update_mode_buttons() {
		this.$mode.find("button").removeClass("eag-active");
		this.$mode.find(`button[data-mode="${this.mode}"]`).addClass("eag-active");
	}

	/* ------------------------------ containers ----------------------------- */

	make_container() {
		this.$status = $('<div class="eag-status"></div>').appendTo(this.page.main);
		this.$content = $('<div class="eag-content"></div>').appendTo(this.page.main);
		this.$more = $('<div class="eag-more"></div>').appendTo(this.page.main);
	}

	set_status(message) {
		this.$status.text(message || "");
	}

	show_error(error) {
		let message = error && (error.message || error.exc);
		try {
			if (!message && error && error._server_messages) {
				message = JSON.parse(error._server_messages)
					.map((entry) => JSON.parse(entry).message)
					.join("<br>");
			}
		} catch (e) {
			// ignore
		}
		frappe.msgprint({ message: message || __("Something went wrong"), indicator: "red" });
	}

	/* -------------------------------- tweaks ------------------------------- */

	make_tweaks() {
		this.tweaks = {
			density: localStorage.getItem("eag_density") || "relaxed",
			photo: localStorage.getItem("eag_photo") || "portrait",
		};

		const $tweaks = $(`
			<div class="eag-tweaks">
				<div class="eag-tweaks-title">
					<span>${__("Display")}</span>
					<svg class="eag-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor"
						stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
						<polyline points="6 9 12 15 18 9"></polyline>
					</svg>
				</div>
				<div class="eag-tweaks-body">
					<div class="eag-tweaks-row">
						<span>${__("Density")}</span>
						<div class="eag-seg eag-seg-sm" data-tweak="density">
							<button type="button" data-value="compact">${__("Compact")}</button>
							<button type="button" data-value="relaxed">${__("Relaxed")}</button>
						</div>
					</div>
					<div class="eag-tweaks-row">
						<span>${__("Photo")}</span>
						<div class="eag-seg eag-seg-sm" data-tweak="photo">
							<button type="button" data-value="portrait">${__("Portrait")}</button>
							<button type="button" data-value="square">${__("Square")}</button>
						</div>
					</div>
				</div>
			</div>
		`).appendTo(document.body);

		$tweaks.find(".eag-tweaks-title").on("click", () => {
			$tweaks.toggleClass("eag-collapsed");
		});

		$tweaks.on("click", ".eag-seg button", (event) => {
			const $button = $(event.currentTarget);
			const axis = $button.closest(".eag-seg").attr("data-tweak");
			this.tweaks[axis] = $button.attr("data-value");
			this.apply_tweaks();
		});

		this.$tweaks = $tweaks;
		this.apply_tweaks();
	}

	apply_tweaks() {
		localStorage.setItem("eag_density", this.tweaks.density);
		localStorage.setItem("eag_photo", this.tweaks.photo);

		this.page.main
			.toggleClass("eag-density-compact", this.tweaks.density === "compact")
			.toggleClass("eag-photo-square", this.tweaks.photo === "square");

		this.$tweaks.find(".eag-seg").each((_, seg) => {
			const axis = $(seg).attr("data-tweak");
			$(seg)
				.find("button")
				.removeClass("eag-active")
				.filter(`[data-value="${this.tweaks[axis]}"]`)
				.addClass("eag-active");
		});
	}

	/* -------------------------------- state -------------------------------- */

	get_filters() {
		return {
			company: this.$company.val() || null,
			from_date: this.$from.val(),
			to_date: this.$to.val(),
			search: this.search_value || null,
			log_type: this.$log_type.val() || null,
			face_verified: this.$face.val() || null,
		};
	}

	days_in_range() {
		const from = frappe.datetime.str_to_obj(this.$from.val());
		const to = frappe.datetime.str_to_obj(this.$to.val());
		return frappe.datetime.get_diff(to, from) + 1;
	}

	effective_mode() {
		if (this.mode !== "auto") return this.mode;
		return this.days_in_range() <= 2 ? "gallery" : "list";
	}

	refresh() {
		this.request_id += 1;
		if (this.view === "employee") return this.load_daily_cards(this.request_id);
		if (this.effective_mode() === "gallery") return this.load_gallery(true, this.request_id);
		return this.load_summary(true, this.request_id);
	}

	/* ------------------------------- gallery ------------------------------- */

	async load_gallery(reset, request_id) {
		const id = request_id || this.request_id;
		if (reset) {
			this.start = 0;
			this.current_rows = [];
			this.$content.empty();
			this.$more.empty();
			this.$grid = null;
		}
		this.set_status(__("Loading..."));
		try {
			const result = await frappe.xcall("hrms.api.get_employee_checkin_gallery", {
				...this.get_filters(),
				start: this.start,
				page_length: this.page_length,
			});
			if (id !== this.request_id) return;
			this.current_rows = this.current_rows.concat(result.rows || []);
			this.render_gallery(result.rows || []);
			this.start = this.current_rows.length;
			this.$more.empty();
			if (result.has_more) this.render_more(() => this.load_gallery(false));
			this.set_status(
				(result.rows || []).length || this.current_rows.length
					? ""
					: __("No check-ins found for the selected filters.")
			);
		} catch (error) {
			if (id !== this.request_id) return;
			this.set_status("");
			this.show_error(error);
		}
	}

	render_gallery(rows) {
		if (!this.$grid) {
			this.$grid = $('<div class="eag-grid"></div>').appendTo(this.$content);
			this.$grid.on("click", ".eag-card", (event) => {
				const name = $(event.currentTarget).attr("data-name");
				const row = this.current_rows.find((entry) => entry.name === name);
				if (row) this.show_logs_modal(row.employee_name || row.employee, [row]);
			});
		}
		rows.forEach((row) => this.$grid.append(this.card_html(row)));
	}

	card_html(row) {
		const photo = row.face_photo
			? `<img class="eag-photo-img" src="${frappe.utils.escape_html(
					row.face_photo
				)}" loading="lazy" alt="">`
			: `<div class="eag-photo-empty">${frappe.utils.escape_html(
					frappe.get_abbr(row.employee_name || row.employee)
				)}</div>`;
		const score =
			row.face_score !== null && row.face_score !== undefined
				? `<div class="eag-line eag-muted">${__("Score")}: ${Number(row.face_score).toFixed(3)}</div>`
				: "";
		const log_type = (row.log_type || "").toLowerCase();

		return `
			<div class="eag-card" data-name="${frappe.utils.escape_html(row.name)}">
				<div class="eag-photo">
					${photo}
					<span class="eag-log eag-log-${log_type}">${frappe.utils.escape_html(row.log_type || "")}</span>
					<span class="eag-badge-wrap">${this.attendance_badge(row)}</span>
				</div>
				<div class="eag-card-body">
					<div class="eag-name">${frappe.utils.escape_html(
						row.employee_name || row.employee
					)}</div>
					<div class="eag-line"><b>${frappe.datetime.str_to_user(row.time)}</b></div>
					${score}
				</div>
			</div>`;
	}

	attendance_badge(row) {
		if (row.late_entry) {
			return `<span class="eag-badge eag-badge-late">${__("Late")}</span>`;
		}
		const map = {
			Present: ["present", __("Present")],
			"Work From Home": ["present", __("WFH")],
			"Half Day": ["half", __("Half Day")],
			Absent: ["absent", __("Absent")],
			"On Leave": ["leave", __("On Leave")],
		};
		const entry = map[row.attendance_status];
		if (!entry) {
			return `<span class="eag-badge eag-badge-none">${__("No Attendance")}</span>`;
		}
		return `<span class="eag-badge eag-badge-${entry[0]}">${entry[1]}</span>`;
	}

	/* ------------------------------- summary ------------------------------- */

	async load_summary(reset, request_id) {
		const id = request_id || this.request_id;
		if (reset) {
			this.start = 0;
			this.current_rows = [];
			this.$content.empty();
			this.$more.empty();
			this.$list = null;
		}
		this.set_status(__("Loading..."));
		try {
			const filters = this.get_filters();
			const result = await frappe.xcall("hrms.api.get_attendance_summary_by_employee", {
				company: filters.company,
				from_date: filters.from_date,
				to_date: filters.to_date,
				search: filters.search,
				start: this.start,
				page_length: 20,
			});
			if (id !== this.request_id) return;
			this.current_rows = this.current_rows.concat(result.rows || []);
			this.render_summary(result.rows || []);
			this.start = this.current_rows.length;
			this.$more.empty();
			if (result.has_more) this.render_more(() => this.load_summary(false));
			this.set_status(
				(result.rows || []).length || this.current_rows.length
					? ""
					: __("No employees found for the selected filters.")
			);
		} catch (error) {
			if (id !== this.request_id) return;
			this.set_status("");
			this.show_error(error);
		}
	}

	render_summary(rows) {
		if (!this.$list) {
			this.$list = $('<div class="eag-list"></div>').appendTo(this.$content);
			this.$list.on("click", ".eag-row", (event) => {
				const employee = $(event.currentTarget).attr("data-employee");
				const row = this.current_rows.find((entry) => entry.employee === employee);
				if (row) this.open_employee(row);
			});
		}
		rows.forEach((row) => this.$list.append(this.summary_row_html(row)));
	}

	summary_row_html(row) {
		const chip = (kind, label, value) =>
			`<span class="eag-chip eag-chip-${kind}"><b>${value}</b> ${frappe.utils.escape_html(
				label
			)}</span>`;
		return `
			<div class="eag-row" data-employee="${frappe.utils.escape_html(row.employee)}">
				<div class="eag-avatar">${frappe.utils.escape_html(
					frappe.get_abbr(row.employee_name || row.employee)
				)}</div>
				<div class="eag-row-main">
					<div class="eag-name">${frappe.utils.escape_html(
						row.employee_name || row.employee
					)}</div>
					<div class="eag-line eag-muted">${frappe.utils.escape_html(
						row.company || ""
					)}${row.designation ? " · " + frappe.utils.escape_html(row.designation) : ""}</div>
				</div>
				<div class="eag-chips">
					${chip("present", __("Present"), row.present)}
					${chip("late", __("Late"), row.late)}
					${chip("half", __("Half Day"), row.half_day)}
					${chip("absent", __("Absent"), row.absent)}
					${chip("leave", __("On Leave"), row.on_leave)}
					${chip("logs", __("Logs"), row.logs)}
				</div>
				<button class="btn btn-xs btn-default eag-open">${__("Detail")}</button>
			</div>`;
	}

	/* ------------------------------ drill-down ----------------------------- */

	open_employee(row) {
		this.view = "employee";
		this.selected_employee = row;
		this.refresh();
	}

	back_to_main() {
		this.view = "main";
		this.selected_employee = null;
		this.refresh();
	}

	async load_daily_cards(request_id) {
		const id = request_id || this.request_id;
		this.$content.empty();
		this.$more.empty();
		this.set_status(__("Loading..."));
		try {
			const filters = this.get_filters();
			const result = await frappe.xcall("hrms.api.get_attendance_daily_cards", {
				employee: this.selected_employee.employee,
				from_date: filters.from_date,
				to_date: filters.to_date,
			});
			if (id !== this.request_id) return;
			this.render_employee_header(result.employee);
			this.$grid = $('<div class="eag-grid"></div>').appendTo(this.$content);
			(result.days || []).forEach((day) => this.$grid.append(this.day_card_html(day)));
			this.$grid.on("click", ".eag-card", (event) => {
				const date = $(event.currentTarget).attr("data-date");
				const day = (result.days || []).find((entry) => entry.date === date);
				if (day) {
					this.show_logs_modal(
						`${result.employee.employee_name || result.employee.name} · ${frappe.datetime.str_to_user(
							day.date
						)}`,
						day.logs || []
					);
				}
			});
			this.set_status((result.days || []).length ? "" : __("No attendance in this range."));
		} catch (error) {
			if (id !== this.request_id) return;
			this.set_status("");
			this.show_error(error);
		}
	}

	render_employee_header(employee) {
		const $header = $(`
			<div class="eag-employee-header">
				<button class="btn btn-xs btn-default eag-back">${__("Back")}</button>
				<div class="eag-employee-title">
					<b>${frappe.utils.escape_html(employee.employee_name || employee.name)}</b>
					<span class="eag-muted">${frappe.utils.escape_html(
						employee.company || ""
					)}${employee.designation ? " · " + frappe.utils.escape_html(employee.designation) : ""}</span>
				</div>
			</div>
		`).prependTo(this.$content);
		$header.find(".eag-back").on("click", () => this.back_to_main());
	}

	day_card_html(day) {
		const reference = day.first_in || day.last_out;
		const photo = reference && reference.face_photo
			? `<img class="eag-photo-img" src="${frappe.utils.escape_html(
					reference.face_photo
				)}" loading="lazy" alt="">`
			: `<div class="eag-photo-empty">${frappe.utils.escape_html(
					frappe.get_abbr(this.selected_employee.employee_name || "")
				)}</div>`;
		const time_of = (log) =>
			log ? frappe.datetime.str_to_user(log.time).split(" ").slice(-1)[0] : "-";
		return `
			<div class="eag-card" data-date="${day.date}">
				<div class="eag-photo">
					${photo}
					<span class="eag-badge-wrap">${this.attendance_badge(day)}</span>
				</div>
				<div class="eag-card-body">
					<div class="eag-line"><b>${frappe.datetime.str_to_user(day.date)}</b></div>
					<div class="eag-line eag-muted">${__("In")}: ${time_of(day.first_in)}</div>
					<div class="eag-line eag-muted">${__("Out")}: ${time_of(day.last_out)}</div>
					<div class="eag-line eag-muted">${__("{0} log(s)", [(day.logs || []).length])}</div>
				</div>
			</div>`;
	}

	/* -------------------------------- modal -------------------------------- */

	show_logs_modal(title, logs) {
		const dialog = new frappe.ui.Dialog({
			title: frappe.utils.escape_html(title),
			size: "large",
		});
		const $body = $('<div class="eag-modal"></div>').appendTo(dialog.body);

		if (!(logs || []).length) {
			$body.append(`<div class="eag-muted">${__("No check-in logs for this day.")}</div>`);
		}

		(logs || []).forEach((log) => {
			const photo = log.face_photo
				? `<img class="eag-modal-photo" src="${frappe.utils.escape_html(log.face_photo)}" alt="">`
				: `<div class="eag-modal-photo eag-photo-empty">${frappe.utils.escape_html(
						frappe.get_abbr(log.employee_name || "")
					)}</div>`;
			const map =
				log.latitude && log.longitude
					? `<iframe class="eag-map" src="https://maps.google.com/maps?q=${log.latitude},${log.longitude}&hl=en&z=15&output=embed"></iframe>`
					: "";
			const log_type = (log.log_type || "").toLowerCase();
			$body.append(`
				<div class="eag-modal-log">
					<div class="eag-modal-col">${photo}</div>
					<div class="eag-modal-col">
						<div><span class="eag-log eag-log-${log_type}">${frappe.utils.escape_html(
							log.log_type || ""
						)}</span></div>
						<div class="eag-line"><b>${frappe.datetime.str_to_user(log.time)}</b></div>
						<div class="eag-line eag-muted">${__("Face Verified")}: ${
							log.face_verified ? __("Yes") : __("No")
						}</div>
						${
							log.face_score !== null && log.face_score !== undefined
								? `<div class="eag-line eag-muted">${__("Score")}: ${Number(
										log.face_score
									).toFixed(3)}</div>`
								: ""
						}
						${
							log.latitude && log.longitude
								? `<div class="eag-line eag-muted">${Number(log.latitude).toFixed(5)}, ${Number(
										log.longitude
									).toFixed(5)}</div>`
								: ""
						}
						${map}
					</div>
				</div>
			`);
		});

		dialog.show();
	}

	/* -------------------------------- helpers ------------------------------ */

	render_more(callback) {
		this.$more.empty();
		$(`<button class="btn btn-sm btn-default">${__("Load More")}</button>`)
			.appendTo(this.$more)
			.on("click", (event) => {
				$(event.currentTarget).prop("disabled", true);
				callback();
			});
	}
}
