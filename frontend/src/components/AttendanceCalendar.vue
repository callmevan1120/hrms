<template>
	<div class="flex flex-col w-full gap-5" v-if="calendarEvents.data">
		<div class="text-lg text-gray-800 font-bold">{{ __("Attendance Calendar") }}</div>

		<div class="flex flex-col gap-6 bg-white py-6 px-3.5 rounded-lg border-none">
			<!-- Month Change -->
			<div class="flex flex-row justify-between items-center px-4">
				<Button
					icon="chevron-left"
					variant="ghost"
					@click="firstOfMonth = firstOfMonth.subtract(1, 'M')"
				/>
				<span class="text-lg text-gray-800 font-bold">
					{{ firstOfMonth.format("MMMM") }} {{ firstOfMonth.format("YYYY") }}
				</span>
				<Button
					icon="chevron-right"
					variant="ghost"
					@click="firstOfMonth = firstOfMonth.add(1, 'M')"
				/>
			</div>

			<!-- Calendar -->
			<div class="grid grid-cols-7 gap-y-3">
				<div
					v-for="day in DAYS"
					class="flex justify-center text-gray-600 text-sm font-medium leading-6"
				>
					{{ day }}
				</div>
				<div v-for="_ in firstOfMonth.get('d')" />
				<div v-for="index in firstOfMonth.endOf('M').get('D')">
					<div
						class="h-8 w-8 flex rounded-full mx-auto"
						:class="[
							getEventOnDate(index) && colorMap[getEventOnDate(index)],
							isLate(index) && 'ring-2 ring-orange-400',
						]"
					>
						<span class="text-gray-800 text-sm font-medium m-auto">
							{{ index }}
						</span>
					</div>
				</div>
			</div>

			<hr />

			<!-- Summary -->
			<div class="grid grid-cols-2 gap-3 mx-2">
				<div
					v-for="status in summaryStatuses"
					:key="status"
					class="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2"
				>
					<div class="flex flex-row gap-1.5 items-center min-w-0">
						<span class="rounded-full h-3 w-3 shrink-0" :class="colorMap[status]" />
						<span class="text-gray-600 text-sm font-medium leading-5 truncate">
							{{ __(status) }}
						</span>
					</div>
					<span class="text-gray-800 text-base font-semibold leading-6">
						{{ summary[status] || 0 }}
					</span>
				</div>
			</div>

			<!-- Lateness Summary -->
			<div class="flex flex-col gap-3 mx-2">
				<div class="flex items-center justify-between bg-orange-50 rounded-lg px-3 py-2">
					<div class="flex flex-row gap-1.5 items-center">
						<span class="rounded-full h-3 w-3 bg-orange-400" />
						<span class="text-gray-600 text-sm font-medium leading-5">{{ __("Late") }}</span>
					</div>
					<span class="text-gray-800 text-base font-semibold">{{ __("{0}x", [lateCount]) }}</span>
				</div>
				<div
					v-if="earlyExitCount"
					class="flex items-center justify-between bg-red-50 rounded-lg px-3 py-2"
				>
					<div class="flex flex-row gap-1.5 items-center">
						<span class="rounded-full h-3 w-3 bg-red-300" />
						<span class="text-gray-600 text-sm font-medium leading-5">
							{{ __("Early Exit") }}
						</span>
					</div>
					<span class="text-gray-800 text-base font-semibold">
						{{ __("{0}x", [earlyExitCount]) }}
					</span>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, inject, ref, watch } from "vue"
import { createResource } from "frappe-ui"

const dayjs = inject("$dayjs")
const __ = inject("$translate")
const firstOfMonth = ref(dayjs().date(1).startOf("D"))

const colorMap = {
	Present: "bg-green-300",
	"Work From Home": "bg-green-300",
	"Half Day": "bg-yellow-200",
	Absent: "bg-red-200",
	"On Leave": "bg-blue-300",
	Holiday: "bg-gray-300",
}

// __("Present"), __("Half Day"), __("Absent"), __("On Leave"), __("Work From Home")
const summaryStatuses = ["Present", "Half Day", "Absent", "On Leave"]

const events = computed(() => calendarEvents.data?.events || {})
const lateDays = computed(() => calendarEvents.data?.late_days || [])
const lateCount = computed(() => calendarEvents.data?.late_count || 0)
const earlyExitCount = computed(() => calendarEvents.data?.early_exit_count || 0)

const summary = computed(() => {
	const summary = {}

	for (const status of Object.values(events.value)) {
		let updatedStatus = status === "Work From Home" ? "Present" : status
		if (updatedStatus in summary) {
			summary[updatedStatus] += 1
		} else {
			summary[updatedStatus] = 1
		}
	}

	return summary
})

watch(
	() => firstOfMonth.value,
	() => {
		calendarEvents.fetch()
	}
)

const getEventOnDate = (date) => {
	return events.value[firstOfMonth.value.date(date).format("YYYY-MM-DD")]
}

const isLate = (date) => {
	return lateDays.value.includes(firstOfMonth.value.date(date).format("YYYY-MM-DD"))
}

const getFirstLetter = (s) => Array.from(s.trim())[0] // Unicode

const DAYS = [
	getFirstLetter(__("Sunday")),
	getFirstLetter(__("Monday")),
	getFirstLetter(__("Tuesday")),
	getFirstLetter(__("Wednesday")),
	getFirstLetter(__("Thursday")),
	getFirstLetter(__("Friday")),
	getFirstLetter(__("Saturday")),
]

//resources
const calendarEvents = createResource({
	url: "hrms.api.get_attendance_calendar_events",
	auto: true,

	makeParams() {
		return {
			from_date: firstOfMonth.value.format("YYYY-MM-DD"),
			to_date: firstOfMonth.value.endOf("M").format("YYYY-MM-DD"),
		}
	},
})
</script>
