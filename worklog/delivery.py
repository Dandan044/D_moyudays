"""首次完整生成后的交付询问，同一工作库只提示一次。"""


def first_delivery_questions(con, coverage):
    if not coverage["total"] or coverage["pending"]:
        return ()
    with con:
        marked = con.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES ('first_delivery_prompt_at',CURRENT_TIMESTAMP)"
        ).rowcount
    if not marked:
        return ()
    return (
        "是否创建定时任务更新此网页？可选每日指定时间、每隔一段时间或暂不创建。",
        "是否创建一个打开此网页的桌面快捷方式？",
    )
