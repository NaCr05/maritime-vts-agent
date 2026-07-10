from typing import Dict, Any, List


def judge_vessel_risk(
    speed: float,
    distance_to_restricted_area: float,
    course_change: float
) -> Dict[str, Any]:
    """
    简单船舶风险研判工具。

    参数：
    speed: 船舶航速，单位：节
    distance_to_restricted_area: 距离限制区域的距离，单位：海里
    course_change: 短时间内航向变化，单位：度

    说明：
    这是 Demo 规则，不代表真实业务阈值。
    """

    score = 0
    reasons: List[str] = []
    suggestions: List[str] = []

    # 航速判断
    if speed < 2:
        score += 2
        reasons.append(f"航速为 {speed:.1f} 节，低于 2 节，存在低速异常、徘徊、等待或故障风险。")
    elif speed < 5:
        score += 1
        reasons.append(f"航速为 {speed:.1f} 节，处于较低水平，需要结合场景继续观察。")
    else:
        reasons.append(f"航速为 {speed:.1f} 节，未触发低速异常规则。")

    # 限制区域距离判断
    if distance_to_restricted_area < 0.5:
        score += 3
        reasons.append(
            f"距离限制区域 {distance_to_restricted_area:.2f} 海里，低于 0.5 海里，存在越界或接近敏感区域风险。"
        )
    elif distance_to_restricted_area < 1.0:
        score += 1
        reasons.append(
            f"距离限制区域 {distance_to_restricted_area:.2f} 海里，距离较近，需要持续关注。"
        )
    else:
        reasons.append(
            f"距离限制区域 {distance_to_restricted_area:.2f} 海里，暂未触发接近限制区域规则。"
        )

    # 航向变化判断
    if course_change > 30:
        score += 2
        reasons.append(
            f"航向变化为 {course_change:.1f} 度，超过 30 度，存在异常转向或航迹不稳定风险。"
        )
    elif course_change > 15:
        score += 1
        reasons.append(
            f"航向变化为 {course_change:.1f} 度，存在一定转向变化，需要结合历史轨迹观察。"
        )
    else:
        reasons.append(
            f"航向变化为 {course_change:.1f} 度，未触发明显异常转向规则。"
        )

    # 风险等级
    if score >= 6:
        risk_level = "高风险"
        suggestions.append("建议 VTS 值班人员立即重点关注该船，并结合实时轨迹、通航规则和现场情况进行人工复核。")
    elif score >= 4:
        risk_level = "中高风险"
        suggestions.append("建议 VTS 值班人员持续监控该船轨迹，必要时发出提醒。")
    elif score >= 2:
        risk_level = "中风险"
        suggestions.append("建议继续观察该船后续航速、航向和位置变化。")
    else:
        risk_level = "低风险"
        suggestions.append("当前未触发明显风险规则，可保持常规监控。")

    return {
        "risk_level": risk_level,
        "score": score,
        "reasons": reasons,
        "suggestions": suggestions,
        "disclaimer": "以上判断基于 Demo 规则，不代表真实海事监管结论。真实场景需由 VTS 值班人员结合实时数据和业务规则复核。"
    }
