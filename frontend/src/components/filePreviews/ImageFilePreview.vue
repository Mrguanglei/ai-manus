<template>
    <div class="flex flex-col items-center justify-center gap-6 flex-1 w-full min-h-0">
        <img :src="imageUrl" alt="Image" class="w-full h-full object-contain" />
    </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { getFileDownloadUrl } from '../../api/file';
import type { FileInfo } from '../../api/file';

const props = defineProps<{
    file: FileInfo;
}>();

const imageUrl = ref('');

watch(() => props.file.file_id, async (fileId) => {
    if (!fileId) return;
    imageUrl.value = getFileDownloadUrl(fileId);
}, { immediate: true });
</script>