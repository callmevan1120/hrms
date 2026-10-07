<template>
	<div v-if="usage.data?.length" class="flex flex-col w-full gap-3 px-4">
		<div class="text-lg text-gray-800 font-bold">{{ __("Usage This Year") }}</div>

		<div class="flex flex-col bg-white rounded-lg border-none py-2 px-3.5">
			<div
				v-for="row in usage.data"
				:key="row.leave_type"
				class="flex flex-row items-center justify-between py-2 border-b border-gray-100 last:border-b-0"
			>
				<span class="text-gray-700 text-sm font-medium">
					{{ __(row.leave_type, null, "Leave Type") }}
				</span>
				<span class="text-gray-800 text-sm font-semibold">
					{{ __("{0}x", [row.count]) }} &middot;
					{{ __("{0} day(s)", [formatDays(row.days)]) }}
				</span>
			</div>
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue"
import { createResource } from "frappe-ui"

const __ = inject("$translate")

const usage = createResource({
	url: "hrms.api.get_leave_usage_summary",
	auto: true,
})

const formatDays = (days) => {
	const value = Number(days) || 0
	return Number.isInteger(value) ? value : value.toFixed(1)
}
</script>
