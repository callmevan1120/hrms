<template>
	<div class="flex flex-col bg-white rounded w-full py-6 px-4 border-none">
		<h2 class="text-lg font-bold text-gray-900">
			{{ __("Hey, {0} 👋", [employee?.data?.first_name]) }}
		</h2>

		<template v-if="settings.data?.allow_employee_checkin_from_mobile_app">
			<div class="font-medium text-sm text-gray-500 mt-1.5" v-if="lastLog">
				<span>{{
					__("Last {0} was at {1}", [__(lastLogType), formatTimestamp(lastLog.time)])
				}}</span>
				<span class="whitespace-pre"> &middot; </span>
				<router-link :to="{ name: 'EmployeeCheckinListView' }" v-slot="{ navigate }">
					<span @click="navigate" class="underline">{{ __("View List") }}</span>
				</router-link>
			</div>
			<div v-if="missedCheckout" class="mt-2 text-xs font-medium text-orange-600">
				{{
					__(
						"You have not checked out on {0}. Please raise an Attendance Request to regularize it.",
						[missedCheckoutDate]
					)
				}}
			</div>
			<Button
				class="mt-4 mb-1 drop-shadow-sm py-5 text-base"
				id="open-checkin-modal"
				:loading="checkins.list.loading"
				:disabled="nextAction.action === 'DONE'"
				@click="handleEmployeeCheckin"
			>
				<template #prefix>
					<FeatherIcon :name="nextActionIcon" class="w-4" />
				</template>
				{{ nextAction.label }}
			</Button>
		</template>

		<div v-else class="font-medium text-sm text-gray-500 mt-1.5">
			{{ dayjs().format("ddd, D MMMM, YYYY") }}
		</div>
	</div>

	<ion-modal
		v-if="settings.data?.allow_employee_checkin_from_mobile_app"
		ref="modal"
		trigger="open-checkin-modal"
		:initial-breakpoint="1"
		:breakpoints="[0, 1]"
		@didDismiss="resetFaceState"
	>
		<div
			class="w-full min-h-full flex flex-col items-center justify-start gap-4 px-4 pt-4 pb-10 overflow-y-auto"
		>
			<div class="flex flex-col gap-1.5 mt-2 items-center justify-center">
				<div class="font-bold text-xl">
					{{ dayjs(checkinTimestamp).format("hh:mm:ss a") }}
				</div>
				<div class="font-medium text-gray-500 text-sm">
					{{ dayjs().format("D MMM, YYYY") }}
				</div>
			</div>

			<template v-if="settings.data?.allow_geolocation_tracking">
				<span v-if="locationStatus" class="font-medium text-gray-500 text-sm">
					{{ locationStatus }}
				</span>

				<div class="rounded border-4 translate-z-0 block overflow-hidden w-full h-170">
					<iframe
						width="100%"
						height="170"
						frameborder="0"
						scrolling="no"
						marginheight="0"
						marginwidth="0"
						style="border: 0"
						:src="`https://maps.google.com/maps?q=${latitude},${longitude}&hl=en&z=15&amp;output=embed`"
					>
					</iframe>
				</div>
			</template>

			<template v-if="settings.data?.enable_face_checkin">
				<div
					v-if="!faceStatusChecked || faceStatus.loading"
					class="font-medium text-gray-500 text-sm"
				>
					{{ __("Checking face enrollment...") }}
				</div>

				<template v-else-if="faceStep === 'enroll'">
					<div class="text-sm text-gray-500 text-center">
						{{
							__(
								"Enroll your face to start using face attendance. Your face data is stored securely for attendance verification."
							)
						}}
					</div>
					<FaceCapture
						mode="enroll"
						:samples-required="enrollSamples"
						@captured="handleEnrolled"
					/>
				</template>

				<template v-else-if="faceStep === 'capture'">
					<FaceCapture mode="verify" @captured="handleFaceCaptured" />
				</template>

				<div v-else-if="faceStep === 'confirm'" class="flex flex-col items-center gap-3 w-full">
					<img
						v-if="capturedPhoto"
						:src="capturedPhoto"
						class="w-40 h-40 object-contain bg-black rounded-lg"
					/>
					<div
						class="text-sm font-medium text-center px-2 leading-snug"
						:class="verifyError ? 'text-red-500' : 'text-green-600'"
					>
						{{ confirmStatusText }}
					</div>
					<Button
						:disabled="faceCheckin.loading"
						variant="ghost"
						class="w-full py-4"
						@click="retryFaceCapture"
					>
						{{ __("Retake Face") }}
					</Button>
				</div>
			</template>

			<Button
				v-else
				:loading="checkins.insert.loading"
				variant="solid"
				class="w-full py-5 text-sm disabled:bg-gray-700"
				@click="submitLog(nextAction.action)"
			>
				{{ __("Confirm {0}", [nextAction.label]) }}
			</Button>
		</div>
	</ion-modal>
</template>

<script setup>
import { createListResource, createResource, toast, FeatherIcon } from "frappe-ui"
import { computed, inject, ref, onMounted, onBeforeUnmount } from "vue"
import { IonModal, modalController } from "@ionic/vue"

import FaceCapture from "@/components/FaceCapture.vue"
import { formatTimestamp } from "@/utils/formatters"
import { settings } from "@/data/settings"

const DOCTYPE = "Employee Checkin"

const socket = inject("$socket")
const employee = inject("$employee")
const dayjs = inject("$dayjs")
const __ = inject("$translate")
const checkinTimestamp = ref(null)
const latitude = ref(0)
const longitude = ref(0)
const locationStatus = ref("")

const faceStep = ref("capture")
const faceStatusChecked = ref(false)
const capturedDescriptor = ref(null)
const capturedPhoto = ref(null)
const verifyError = ref("")

const checkins = createListResource({
	doctype: DOCTYPE,
	fields: [
		"name",
		"employee",
		"employee_name",
		"log_type",
		"time",
		"device_id",
		"shift_actual_end",
		"face_verified",
	],
	filters: {
		employee: employee.data.name,
	},
	orderBy: "time desc",
})
checkins.reload()

const faceStatus = createResource({
	url: "hrms.api.face.get_face_status",
	method: "GET",
})

const enrollFace = createResource({
	url: "hrms.api.face.enroll_face",
	method: "POST",
})

const faceCheckin = createResource({
	url: "hrms.api.face.face_checkin",
	method: "POST",
})

const lastLog = computed(() => {
	if (!checkins.data?.length) return {}
	return checkins.data[0]
})

const lastLogType = computed(() => {
	return lastLog?.value?.log_type === "IN" ? "check-in" : "check-out"
})

const openCheckin = computed(() => {
	const last = checkins.data?.[0]
	return last?.log_type === "IN" ? last : null
})

const isWithinCheckoutWindow = (log) => {
	const reference = log?.shift_actual_end || log?.time
	return reference ? dayjs().isBefore(dayjs(reference).endOf("day")) : false
}

const missedCheckout = computed(() => {
	return openCheckin.value && !isWithinCheckoutWindow(openCheckin.value)
})

const missedCheckoutDate = computed(() => {
	return dayjs(openCheckin.value?.time).format("D MMM YYYY")
})

const todayLogs = computed(() =>
	(checkins.data || []).filter((log) => dayjs(log.time).isSame(dayjs(), "day"))
)

const hasCheckedInToday = computed(() => todayLogs.value.some((log) => log.log_type === "IN"))

const nextAction = computed(() => {
	if (openCheckin.value && isWithinCheckoutWindow(openCheckin.value)) {
		return { action: "OUT", label: __("Check Out") }
	}
	// one check-in (and one check-out) per day for self-service check-ins
	if (hasCheckedInToday.value) {
		return { action: "DONE", label: __("Attendance Completed") }
	}
	return { action: "IN", label: __("Check In") }
})

const nextActionIcon = computed(() => {
	if (nextAction.value.action === "IN") return "arrow-right-circle"
	if (nextAction.value.action === "OUT") return "arrow-left-circle"
	return "check-circle"
})

const enrollSamples = computed(() => settings.data?.face_enroll_samples || 3)

function handleLocationSuccess(position) {
	latitude.value = position.coords.latitude
	longitude.value = position.coords.longitude

	locationStatus.value = [
		__("Latitude: {0}°", [Number(latitude.value).toFixed(5)]),
		__("Longitude: {0}°", [Number(longitude.value).toFixed(5)]),
	].join(", ")
}

function handleLocationError(error) {
	locationStatus.value = __("Unable to retrieve your location")
	if (error) locationStatus.value += `: ERROR(${error.code}): ${error.message}`
}

const fetchLocation = () => {
	if (!navigator.geolocation) {
		locationStatus.value = __("Geolocation is not supported by your current browser")
	} else {
		locationStatus.value = __("Locating...")
		navigator.geolocation.getCurrentPosition(handleLocationSuccess, handleLocationError)
	}
}

const ensureLocation = () => {
	if (!settings.data?.allow_geolocation_tracking) return true
	if (latitude.value && longitude.value) return true

	toast({
		title: __("Error"),
		text: __("Unable to retrieve your location. Please wait or try again."),
		icon: "alert-circle",
		position: "bottom-center",
		iconClasses: "text-red-500",
	})
	return false
}

function resetFaceState() {
	faceStep.value = "capture"
	capturedDescriptor.value = null
	capturedPhoto.value = null
	verifyError.value = ""
}

const confirmStatusText = computed(() => {
	if (faceCheckin.loading) return __("Verifying face...")
	if (verifyError.value) return verifyError.value
	if (settings.data?.allow_geolocation_tracking && !(latitude.value && longitude.value)) {
		return __("Waiting for your location...")
	}
	return __("Face verified. Submitting attendance...")
})

const handleEmployeeCheckin = () => {
	if (nextAction.value.action === "DONE") return

	checkinTimestamp.value = dayjs().format("YYYY-MM-DD HH:mm:ss")
	resetFaceState()

	// always try to capture the location for the check-in history (best effort)
	fetchLocation()

	if (settings.data?.enable_face_checkin) {
		faceStatusChecked.value = false
		faceStatus
			.fetch()
			.then((data) => {
				faceStep.value = data?.enrolled ? "capture" : "enroll"
			})
			.catch(() => {
				faceStep.value = "capture"
			})
			.finally(() => {
				faceStatusChecked.value = true
			})
	}
}

const handleFaceCaptured = async ({ descriptors, photo }) => {
	capturedDescriptor.value = descriptors[0]
	capturedPhoto.value = photo
	verifyError.value = ""
	faceStep.value = "confirm"

	// give geolocation a moment to resolve so the attendance record carries the location
	const deadline = Date.now() + 3000
	while (!(latitude.value && longitude.value) && Date.now() < deadline) {
		await new Promise((resolve) => setTimeout(resolve, 250))
	}

	const hasLocation = latitude.value && longitude.value
	if (hasLocation || !settings.data?.allow_geolocation_tracking) {
		submitFaceCheckin()
	}
}

const retryFaceCapture = () => {
	capturedDescriptor.value = null
	capturedPhoto.value = null
	verifyError.value = ""
	faceStep.value = "capture"
}

const handleEnrolled = ({ descriptors, photo }) => {
	enrollFace.submit(
		{
			employee: employee.data.name,
			descriptors: JSON.stringify(descriptors),
			photo,
		},
		{
			onSuccess() {
				toast({
					title: __("Success"),
					text: __("Face enrolled successfully!"),
					icon: "check-circle",
					position: "bottom-center",
					iconClasses: "text-green-500",
				})
				faceStep.value = "capture"
			},
			onError(error) {
				const messages = error.messages?.length ? error.messages : [__("Face enrollment failed!")]
				for (const message of messages) {
					toast({
						title: __("Error"),
						text: message,
						icon: "alert-circle",
						position: "bottom-center",
						iconClasses: "text-red-500",
					})
				}
			},
		}
	)
}

const submitFaceCheckin = () => {
	if (!ensureLocation()) return

	const actionLabel = nextAction.value.action === "IN" ? __("Check-in") : __("Check-out")
	faceCheckin.submit(
		{
			log_type: nextAction.value.action,
			descriptor: JSON.stringify(capturedDescriptor.value),
			latitude: latitude.value || null,
			longitude: longitude.value || null,
			photo: capturedPhoto.value,
		},
		{
			onSuccess(data) {
				if (!data?.name) {
					toast({
						title: __("Error"),
						text: __("{0} failed!", [actionLabel]),
						icon: "alert-circle",
						position: "bottom-center",
						iconClasses: "text-red-500",
					})
					return
				}

				modalController.dismiss()
				checkins.reload()
				resetFaceState()
				toast({
					title: __("Success"),
					text: __("{0} successful!", [actionLabel]),
					icon: "check-circle",
					position: "bottom-center",
					iconClasses: "text-green-500",
				})
			},
			onError(error) {
				const messages = error.messages?.length
					? error.messages
					: [__("{0} failed!", [actionLabel])]
				verifyError.value = messages[0] || __("{0} failed!", [actionLabel])
				for (const message of messages) {
					toast({
						title: __("Error"),
						text: message,
						icon: "alert-circle",
						position: "bottom-center",
						iconClasses: "text-red-500",
					})
				}
			},
		}
	)
}

const submitLog = (logType) => {
	if (!ensureLocation()) return

	const actionLabel = logType === "IN" ? __("Check-in") : __("Check-out")

	checkins.insert.submit(
		{
			employee: employee.data.name,
			log_type: logType,
			time: dayjs().format("YYYY-MM-DD HH:mm:ss"),
			latitude: latitude.value,
			longitude: longitude.value,
		},
		{
			onSuccess(data) {
				if (!data?.name) {
					toast({
						title: __("Error"),
						text: __("{0} failed!", [actionLabel]),
						icon: "alert-circle",
						position: "bottom-center",
						iconClasses: "text-red-500",
					})
					return
				}

				modalController.dismiss()
				checkins.reload()
				toast({
					title: __("Success"),
					text: __("{0} successful!", [actionLabel]),
					icon: "check-circle",
					position: "bottom-center",
					iconClasses: "text-green-500",
				})
			},
			onError(error) {
				const messages = error.messages?.length
					? error.messages
					: [__("{0} failed!", [actionLabel])]
				for (const message of messages) {
					toast({
						title: __("Error"),
						text: message,
						icon: "alert-circle",
						position: "bottom-center",
						iconClasses: "text-red-500",
					})
				}
			},
		}
	)
}

onMounted(() => {
	socket.emit("doctype_subscribe", DOCTYPE)
	socket.on("list_update", (data) => {
		if (data.doctype == DOCTYPE) {
			checkins.reload()
		}
	})
})

onBeforeUnmount(() => {
	socket.emit("doctype_unsubscribe", DOCTYPE)
	socket.off("list_update")
})
</script>
