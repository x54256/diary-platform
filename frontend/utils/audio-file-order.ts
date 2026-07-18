type OrderedFile = Pick<File, 'name' | 'lastModified'>

/**
 * 浏览器不会暴露文件创建时间；以可获得的最后修改时间作为默认顺序。
 */
export const orderAudioFiles = <T extends OrderedFile>(files: T[]): T[] => [...files].sort((left, right) =>
  left.lastModified - right.lastModified || left.name.localeCompare(right.name, 'zh-CN'),
)
