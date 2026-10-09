import type { Category, KnowledgeTag, RetrievalMetadataFilter } from '../api/client'

const FORMAT_OPTIONS: Array<[RetrievalMetadataFilter['formats'][number], string]> = [
  ['pdf', 'PDF'], ['docx', 'Word'], ['markdown', 'Markdown'], ['text', 'TXT'], ['table', '表格'], ['presentation', '演示文稿'],
]

function toLocalInput(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function fromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : undefined
}

export function RetrievalMetadataFilterControls({
  value, categories, tags, disabled = false, onChange,
}: {
  value: RetrievalMetadataFilter
  categories: Category[]
  tags: KnowledgeTag[]
  disabled?: boolean
  onChange: (value: RetrievalMetadataFilter) => void
}) {
  const selectedCount = value.category_ids.length + value.tag_ids.length + value.formats.length +
    Number(value.version_min != null) + Number(value.version_max != null) + Number(value.valid_from != null) + Number(value.valid_to != null)
  const validRangeError = !!value.valid_from && !!value.valid_to && Date.parse(value.valid_from) >= Date.parse(value.valid_to)
  const versionRangeError = value.version_min != null && value.version_max != null && value.version_min > value.version_max

  const toggle = (field: 'category_ids' | 'tag_ids', id: string, checked: boolean) => {
    const current = value[field]
    onChange({ ...value, [field]: checked ? [...new Set([...current, id])] : current.filter(item => item !== id) })
  }

  return <details className='v2-metadata-filter'>
    <summary aria-label='打开资料范围筛选'>资料范围筛选{selectedCount ? ` · ${selectedCount} 项` : ' · 全部资料'}</summary>
    <p className='v2-field-help'>同一组内任一项匹配即可；分类、标签、格式、版本和有效期各组同时生效。资料的权限、启用状态和当前有效期始终强制检查。</p>
    <div className='v2-metadata-filter-grid'>
      <fieldset disabled={disabled}>
        <legend>分类</legend>
        {categories.length ? categories.map(item => <label key={item.id} className='v2-filter-option'>
          <input data-v2-control type='checkbox' checked={value.category_ids.includes(item.id)} onChange={event => toggle('category_ids', item.id, event.target.checked)} />
          <span>{item.display_name || item.name}</span>
        </label>) : <small>当前空间还没有分类。</small>}
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>标签</legend>
        {tags.length ? tags.map(item => <label key={item.id} className='v2-filter-option'>
          <input data-v2-control type='checkbox' checked={value.tag_ids.includes(item.id)} onChange={event => toggle('tag_ids', item.id, event.target.checked)} />
          <span>{item.name}</span>
        </label>) : <small>当前空间还没有标签。</small>}
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>文件类型</legend>
        {FORMAT_OPTIONS.map(([format, label]) => <label key={format} className='v2-filter-option'>
          <input data-v2-control type='checkbox' checked={value.formats.includes(format)} onChange={event => {
            const formats = event.target.checked ? [...new Set([...value.formats, format])] : value.formats.filter(item => item !== format)
            onChange({ ...value, formats })
          }} />
          <span>{label}</span>
        </label>)}
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>活动版本号</legend>
        <div className='v2-metadata-number-range'>
          <label>从<input data-v2-control type='number' min={1} max={10000} step={1} value={value.version_min ?? ''} onChange={event => onChange({ ...value, version_min: event.target.value ? Number(event.target.value) : undefined })} /></label>
          <label>到<input data-v2-control type='number' min={1} max={10000} step={1} value={value.version_max ?? ''} onChange={event => onChange({ ...value, version_max: event.target.value ? Number(event.target.value) : undefined })} /></label>
        </div>
        {versionRangeError && <small className='v2-field-error' role='alert'>版本起始值不能大于结束值。</small>}
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>有效时间范围</legend>
        <div className='v2-metadata-date-range'>
          <label>从<input data-v2-control type='datetime-local' value={toLocalInput(value.valid_from)} onChange={event => onChange({ ...value, valid_from: fromLocalInput(event.target.value) })} /></label>
          <label>到<input data-v2-control type='datetime-local' value={toLocalInput(value.valid_to)} onChange={event => onChange({ ...value, valid_to: fromLocalInput(event.target.value) })} /></label>
        </div>
        {validRangeError && <small className='v2-field-error' role='alert'>开始时间必须早于结束时间。</small>}
        <small>按资料有效期与所选时间范围是否重合筛选；已失效资料仍不会进入检索。</small>
      </fieldset>
    </div>
    <div className='v2-row'><button data-native-button type='button' className='v2-text-button' disabled={disabled || selectedCount === 0} onClick={() => onChange({ category_ids: [], tag_ids: [], formats: [], version_min: undefined, version_max: undefined, valid_from: undefined, valid_to: undefined })}>清空筛选</button></div>
  </details>
}
