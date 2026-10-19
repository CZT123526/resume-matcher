// ECharts 按需封装（T40）：只引柱状图所需模块，避免整包进 bundle。
// 用法：<Chart option={option} height={260} />，option 变化自动 setOption，
// 容器尺寸变化自动 resize，卸载时 dispose。渲染异常静默降级为空块（图表失败不挡页面主功能）。
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import {
  GridComponent, MarkLineComponent, TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

export default function Chart({ option, height = 260 }) {
  const ref = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!ref.current) return undefined
    try {
      chartRef.current = echarts.init(ref.current)
    } catch {
      return undefined
    }
    const onResize = () => chartRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!chartRef.current || !option) return
    try {
      chartRef.current.setOption(option, true)
    } catch {
      /* option 异常不拖垮页面 */
    }
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}
