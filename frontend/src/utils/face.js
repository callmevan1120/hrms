import * as faceapi from "@vladmandic/face-api"

export const FACE_MODELS_URL = "/assets/hrms/face/models"

let modelsPromise = null

export function loadFaceModels() {
	if (!modelsPromise) {
		modelsPromise = Promise.all([
			faceapi.nets.tinyFaceDetector.loadFromUri(FACE_MODELS_URL),
			faceapi.nets.faceLandmark68Net.loadFromUri(FACE_MODELS_URL),
			faceapi.nets.faceRecognitionNet.loadFromUri(FACE_MODELS_URL),
		]).catch((error) => {
			modelsPromise = null
			throw error
		})
	}
	return modelsPromise
}

export const detectorOptions = () =>
	new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 })

export async function detectFace(input) {
	return await faceapi
		.detectSingleFace(input, detectorOptions())
		.withFaceLandmarks()
		.withFaceDescriptor()
}

export function capturePhoto(input, width = 480) {
	const sourceWidth = input.videoWidth || input.naturalWidth || input.width
	const sourceHeight = input.videoHeight || input.naturalHeight || input.height
	const canvas = document.createElement("canvas")
	canvas.width = width
	canvas.height = Math.round((sourceHeight / sourceWidth) * width)
	canvas.getContext("2d").drawImage(input, 0, 0, canvas.width, canvas.height)
	return canvas.toDataURL("image/jpeg", 0.8)
}

export function descriptorToArray(descriptor) {
	return Array.from(descriptor)
}
