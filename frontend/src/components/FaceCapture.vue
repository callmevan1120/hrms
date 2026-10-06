<template>
	<div class="flex flex-col gap-3 w-full items-center">
		<div class="relative w-full overflow-hidden rounded-lg border border-gray-200 bg-black">
			<video
				v-show="cameraActive"
				ref="videoEl"
				class="w-full max-h-80 object-cover"
				autoplay
				muted
				playsinline
			/>
			<canvas
				v-show="cameraActive && faceDetected"
				ref="overlayEl"
				class="absolute inset-0 w-full h-full pointer-events-none"
			/>
			<img v-if="lastSamplePhoto" :src="lastSamplePhoto" class="w-full max-h-80 object-cover" />
			<div
				v-if="!cameraActive && !lastSamplePhoto"
				class="flex items-center justify-center h-64 px-6 text-center text-sm text-gray-300"
			>
				{{ statusText }}
			</div>
		</div>

		<div class="text-sm font-medium text-center" :class="statusClass">
			{{ statusText }}
		</div>

		<input
			ref="fileInput"
			type="file"
			accept="image/*"
			capture="user"
			class="hidden"
			@change="handleFileSelect"
		/>

		<div class="flex flex-row gap-2 w-full">
			<Button
				v-if="cameraActive"
				variant="solid"
				class="w-full py-4"
				:disabled="!faceDetected || capturing"
				:loading="capturing"
				@click="captureSample"
			>
				{{ captureLabel }}
			</Button>
			<Button
				v-if="fallbackNeeded"
				variant="outline"
				class="w-full py-4"
				:loading="capturing"
				@click="openFilePicker"
			>
				{{ __("Take Photo") }}
			</Button>
			<Button
				v-if="lastSamplePhoto && !fallbackNeeded"
				variant="ghost"
				class="py-4"
				@click="resetCapture"
			>
				{{ __("Retake") }}
			</Button>
		</div>

		<div v-if="samplesRequired > 1" class="text-xs text-gray-500">
			{{ __("Samples: {0}/{1}", [samples.length, samplesRequired]) }}
		</div>
	</div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from "vue"
import { Button } from "frappe-ui"
import { detectSingleFace } from "@vladmandic/face-api"

import {
	capturePhoto,
	descriptorToArray,
	detectFace,
	detectorOptions,
	loadFaceModels,
} from "@/utils/face"

const props = defineProps({
	mode: {
		type: String,
		default: "verify", // verify | enroll
	},
	samplesRequired: {
		type: Number,
		default: 1,
	},
})

const emit = defineEmits(["captured"])

const __ = inject("$translate")

const videoEl = ref(null)
const overlayEl = ref(null)
const fileInput = ref(null)

const cameraActive = ref(false)
const fallbackNeeded = ref(false)
const faceDetected = ref(false)
const capturing = ref(false)
const lastSamplePhoto = ref(null)
const statusText = ref("")
const statusKind = ref("info")
const samples = ref([])
const samplesPhoto = ref(null)

let cameraStream = null
let detectionTimer = null

const statusClass = computed(() => {
	return {
		"text-gray-500": statusKind.value === "info",
		"text-green-600": statusKind.value === "success",
		"text-red-500": statusKind.value === "error",
		"text-orange-500": statusKind.value === "warn",
	}
})

const captureLabel = computed(() => {
	if (props.mode === "enroll" && props.samplesRequired > 1) {
		return __("Capture Sample {0}", [samples.value.length + 1])
	}
	return __("Verify Face")
})

function setStatus(text, kind = "info") {
	statusText.value = text
	statusKind.value = kind
}

function stopCamera() {
	if (detectionTimer) {
		clearInterval(detectionTimer)
		detectionTimer = null
	}
	if (cameraStream) {
		cameraStream.getTracks().forEach((track) => track.stop())
		cameraStream = null
	}
	cameraActive.value = false
	faceDetected.value = false
}

async function startCamera() {
	try {
		cameraStream = await navigator.mediaDevices.getUserMedia({
			video: { facingMode: "user", width: { ideal: 640 } },
			audio: false,
		})
		videoEl.value.srcObject = cameraStream
		cameraActive.value = true
		fallbackNeeded.value = false
		setStatus(__("Position your face in front of the camera"), "info")
		startDetectionLoop()
	} catch (error) {
		fallbackNeeded.value = true
		cameraActive.value = false
		setStatus(__("Camera is not available. Please take a photo instead."), "warn")
		if (fileInput.value) fileInput.value.value = ""
	}
}

function startDetectionLoop() {
	detectionTimer = setInterval(async () => {
		if (!videoEl.value || !cameraActive.value || capturing.value) return
		try {
			const detection = await detectSingleFace(
				videoEl.value,
				detectorOptions()
			).withFaceLandmarks()
			faceDetected.value = Boolean(detection)
			drawBox(detection)
		} catch (error) {
			faceDetected.value = false
		}
	}, 700)
}

function drawBox(detection) {
	const canvas = overlayEl.value
	const video = videoEl.value
	if (!canvas || !video || !video.videoWidth) return

	const displayWidth = video.clientWidth
	const displayHeight = video.clientHeight
	canvas.width = displayWidth
	canvas.height = displayHeight

	const context = canvas.getContext("2d")
	context.clearRect(0, 0, canvas.width, canvas.height)
	if (!detection) return

	const box = detection.detection.box
	const scaleX = displayWidth / video.videoWidth
	const scaleY = displayHeight / video.videoHeight
	context.strokeStyle = "#22c55e"
	context.lineWidth = 3
	context.strokeRect(box.x * scaleX, box.y * scaleY, box.width * scaleX, box.height * scaleY)
}

async function captureSample() {
	if (capturing.value) return
	capturing.value = true
	try {
		const detection = await detectFace(videoEl.value)
		if (!detection) {
			setStatus(__("Face not detected. Please try again."), "warn")
			return
		}

		const photo = capturePhoto(videoEl.value)
		samples.value.push(descriptorToArray(detection.descriptor))
		samplesPhoto.value = samplesPhoto.value || photo
		lastSamplePhoto.value = photo

		if (samples.value.length >= props.samplesRequired) {
			stopCamera()
			emit("captured", {
				descriptors: samples.value,
				photo: samplesPhoto.value,
			})
		} else {
			setStatus(
				__("Sample {0}/{1} captured. Move your head slightly and capture again.", [
					samples.value.length,
					props.samplesRequired,
				]),
				"success"
			)
			setTimeout(() => {
				lastSamplePhoto.value = null
				if (cameraActive.value) {
					setStatus(__("Position your face in front of the camera"), "info")
				}
			}, 1200)
		}
	} catch (error) {
		setStatus(__("Face detection failed. Please try again."), "error")
	} finally {
		capturing.value = false
	}
}

function openFilePicker() {
	fileInput.value?.click()
}

async function handleFileSelect(event) {
	const file = event.target.files?.[0]
	if (!file) return

	capturing.value = true
	try {
		const image = await loadImageFromFile(file)
		const detection = await detectFace(image)
		if (!detection) {
			setStatus(__("Face not detected in the photo. Please try again."), "warn")
			return
		}

		const photo = capturePhoto(image)
		samples.value.push(descriptorToArray(detection.descriptor))
		samplesPhoto.value = samplesPhoto.value || photo
		lastSamplePhoto.value = photo

		if (samples.value.length >= props.samplesRequired) {
			emit("captured", {
				descriptors: samples.value,
				photo: samplesPhoto.value,
			})
		} else {
			setStatus(
				__("Sample {0}/{1} captured. Take another photo.", [
					samples.value.length,
					props.samplesRequired,
				]),
				"success"
			)
		}
	} catch (error) {
		setStatus(__("Face detection failed. Please try again."), "error")
	} finally {
		capturing.value = false
		if (fileInput.value) fileInput.value.value = ""
	}
}

function loadImageFromFile(file) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader()
		reader.onload = () => {
			const image = new Image()
			image.onload = () => resolve(image)
			image.onerror = reject
			image.src = reader.result
		}
		reader.onerror = reject
		reader.readAsDataURL(file)
	})
}

function resetCapture() {
	samples.value = []
	samplesPhoto.value = null
	lastSamplePhoto.value = null
	if (!cameraStream) startCamera()
	else setStatus(__("Position your face in front of the camera"), "info")
}

onMounted(async () => {
	setStatus(__("Loading face models..."), "info")
	try {
		await loadFaceModels()
	} catch (error) {
		setStatus(__("Failed to load face models. Please check your connection."), "error")
		return
	}

	if (!navigator.mediaDevices?.getUserMedia) {
		fallbackNeeded.value = true
		setStatus(__("Camera is not supported. Please take a photo instead."), "warn")
		return
	}

	await startCamera()
})

onBeforeUnmount(() => {
	stopCamera()
})
</script>
