import * as faceapi from "@vladmandic/face-api"

export const FACE_MODELS_URL = "/assets/hrms/face/models"

let modelsPromise = null

export function loadFaceModels() {
	if (!modelsPromise) {
		modelsPromise = Promise.all([
			faceapi.nets.tinyFaceDetector.loadFromUri(FACE_MODELS_URL),
			faceapi.nets.faceLandmark68Net.loadFromUri(FACE_MODELS_URL),
			faceapi.nets.faceRecognitionNet.loadFromUri(FACE_MODELS_URL),
		])
			.then(async () => {
				try {
					await faceapi.tf.setBackend("webgl")
					await faceapi.tf.ready()
				} catch (error) {
					// fall back to the default backend (cpu)
				}
				return faceapi
			})
			.catch((error) => {
				modelsPromise = null
				throw error
			})
	}
	return modelsPromise
}

// lightweight options for the live "face present" indicator
export const detectorOptions = () =>
	new faceapi.TinyFaceDetectorOptions({ inputSize: 160, scoreThreshold: 0.5 })

// higher resolution options for enrollment/verification captures: better landmarks
// mean better face alignment and a more discriminative face descriptor
export const captureDetectorOptions = () =>
	new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 })

export async function detectFace(input) {
	return await faceapi
		.detectSingleFace(input, captureDetectorOptions())
		.withFaceLandmarks()
		.withFaceDescriptor()
}

export function snapshotCanvas(input, width = 640) {
	const sourceWidth = input.videoWidth || input.naturalWidth || input.width || width
	const sourceHeight = input.videoHeight || input.naturalHeight || input.height || width
	const canvas = document.createElement("canvas")
	canvas.width = width
	canvas.height = Math.max(1, Math.round((sourceHeight / sourceWidth) * width))
	canvas.getContext("2d").drawImage(input, 0, 0, canvas.width, canvas.height)
	return canvas
}

export function capturePhoto(input, width = 480) {
	return snapshotCanvas(input, width).toDataURL("image/jpeg", 0.8)
}

export function descriptorToArray(descriptor) {
	return Array.from(descriptor)
}
