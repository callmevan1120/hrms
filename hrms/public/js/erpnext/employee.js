// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee", {
	refresh: function (frm) {
		frm.set_query("payroll_cost_center", function () {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0,
				},
			};
		});

		// filter advance account based on salary currency
		if (frm.doc.salary_currency) {
			frm.set_query("employee_advance_account", function () {
				return {
					filters: {
						root_type: "Asset",
						is_group: 0,
						company: frm.doc.company,
						account_currency: frm.doc.salary_currency,
						account_type: "Receivable",
					},
				};
			});
		}
		frm.set_df_property("holiday_list", "hidden", 1);

		// hide naming series field based on hr settings
		frappe.db.get_single_value("HR Settings", "emp_created_by").then((value) => {
			frm.toggle_display("naming_series", value === "Naming Series");
		});

		add_face_attendance_buttons(frm);
	},

	date_of_birth(frm) {
		frm.call({
			method: "hrms.overrides.employee_master.get_retirement_date",
			args: {
				date_of_birth: frm.doc.date_of_birth,
			},
		}).then((r) => {
			if (r && r.message) frm.set_value("date_of_retirement", r.message);
		});
	},
});

const FACE_MODELS_URL = "/assets/hrms/face/models";
const HR_FACE_ROLES = ["HR Manager", "HR User", "System Manager"];

function add_face_attendance_buttons(frm) {
	const is_hr_user = HR_FACE_ROLES.some((role) => frappe.user.has_role(role));
	if (frm.is_new() || !is_hr_user) return;

	frappe.db.get_single_value("HR Settings", "enable_face_checkin").then((enabled) => {
		if (!enabled) return;

		frappe
			.call({
				method: "hrms.api.face.get_face_status",
				args: { employee: frm.doc.name },
			})
			.then((r) => {
				const enrolled = r.message && r.message.enrolled;

				frm.add_custom_button(
					__("Daftarkan Wajah"),
					() => open_face_enrollment_dialog(frm),
					__("Face Attendance")
				);

				if (enrolled) {
					frm.add_custom_button(
						__("Reset Wajah"),
						() => {
							frappe.confirm(
								__("Hapus data wajah {0}? Karyawan harus mendaftar ulang.", [
									frm.doc.employee_name || frm.doc.name,
								]),
								() => {
									frappe.call({
										method: "hrms.api.face.reset_face",
										type: "POST",
										args: { employee: frm.doc.name },
										freeze: true,
										callback: () => {
											frappe.show_alert({
												message: __("Data wajah dihapus"),
												indicator: "green",
											});
											frm.reload_doc();
										},
									});
								}
							);
						},
						__("Face Attendance")
					);
				}
			});
	});
}

function load_face_api() {
	if (window.faceapi) return Promise.resolve(window.faceapi);
	if (!window.__face_api_loading) {
		window.__face_api_loading = new Promise((resolve, reject) => {
			const script = document.createElement("script");
			script.src = "/assets/hrms/face/face-api.min.js";
			script.onload = () => resolve(window.faceapi);
			script.onerror = () => reject(new Error("Gagal memuat face-api"));
			document.head.appendChild(script);
		});
	}
	return window.__face_api_loading;
}

async function setup_face_models(faceapi) {
	await Promise.all([
		faceapi.nets.tinyFaceDetector.loadFromUri(FACE_MODELS_URL),
		faceapi.nets.faceLandmark68Net.loadFromUri(FACE_MODELS_URL),
		faceapi.nets.faceRecognitionNet.loadFromUri(FACE_MODELS_URL),
	]);
}

function open_face_enrollment_dialog(frm) {
	frappe.db.get_single_value("HR Settings", "face_enroll_samples").then((samples) => {
		const required_samples = samples || 3;
		const captured_samples = [];
		let captured_photo = null;
		const dialog = new frappe.ui.Dialog({
			title: __("Daftarkan Wajah: {0}", [frm.doc.employee_name || frm.doc.name]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "camera_area",
					options: `
						<div style="text-align:center">
							<video autoplay muted playsinline
								style="width:100%;max-width:480px;border-radius:8px;background:#000"></video>
							<p class="text-muted face-status" style="margin-top:8px">
								${__("Menyiapkan kamera...")}
							</p>
							<canvas class="face-canvas" style="display:none"></canvas>
						</div>
					`,
				},
			],
			primary_action_label: __("Simpan ({0} sampel)", [required_samples]),
			primary_action: async () => {
				if (captured_samples.length < required_samples) {
					frappe.show_alert({ message: __("Sampel wajah belum lengkap"), indicator: "red" });
					return;
				}
				dialog.get_primary_btn().prop("disabled", true);
				try {
					await frappe.call({
						method: "hrms.api.face.enroll_face",
						type: "POST",
						args: {
							employee: frm.doc.name,
							descriptors: JSON.stringify(captured_samples),
							photo: captured_photo,
						},
					});
					stopCamera();
					dialog.hide();
					frappe.show_alert({ message: __("Wajah berhasil didaftarkan"), indicator: "green" });
					frm.reload_doc();
				} catch (error) {
					dialog.get_primary_btn().prop("disabled", false);
				}
			},
		});

		let camera_stream = null;

		const video = dialog.get_field("camera_area").$wrapper.find("video")[0];
		const canvas = dialog.get_field("camera_area").$wrapper.find("canvas")[0];
		const status = dialog.get_field("camera_area").$wrapper.find(".face-status");

		function stopCamera() {
			if (camera_stream) {
				camera_stream.getTracks().forEach((track) => track.stop());
				camera_stream = null;
			}
		}

		function setStatus(text, color) {
			status.text(text).css("color", color || "");
		}

		dialog.show();
		dialog.get_primary_btn().prop("disabled", true);

		load_face_api()
			.then(async (faceapi) => {
				await setup_face_models(faceapi);
				camera_stream = await navigator.mediaDevices.getUserMedia({
					video: { facingMode: "user", width: 480 },
					audio: false,
				});
				video.srcObject = camera_stream;
				setStatus(__("Posisikan wajah di depan kamera"), "green");
			})
			.catch((error) => {
				setStatus(error.message || __("Tidak dapat mengakses kamera"), "red");
			});

		dialog.$wrapper.on("click", "video", async () => {
			if (!window.faceapi || !camera_stream) return;
			if (captured_samples.length >= required_samples) return;

			const faceapi = window.faceapi;
			const detection = await faceapi
				.detectSingleFace(video, new faceapi.TinyFaceDetectorOptions())
				.withFaceLandmarks()
				.withFaceDescriptor();

			if (!detection) {
				setStatus(__("Wajah tidak terdeteksi, coba lagi"), "orange");
				return;
			}

			captured_samples.push(Array.from(detection.descriptor));
			canvas.width = 480;
			canvas.height = (video.videoHeight / video.videoWidth) * 480;
			canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
			captured_photo = canvas.toDataURL("image/jpeg", 0.8);

			const remaining = required_samples - captured_samples.length;
			setStatus(
				remaining
					? __("Sampel {0}/{1} tersimpan. Gerakkan kepala sedikit lalu klik video lagi.", [
							captured_samples.length,
							required_samples,
						])
					: __("Semua sampel tersimpan. Klik Simpan."),
				remaining ? "green" : "blue"
			);
			dialog.get_primary_btn().prop("disabled", remaining > 0);
		});

		dialog.onhide = () => stopCamera();
	});
}
