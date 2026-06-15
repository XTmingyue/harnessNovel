import re


MAX_CHAPTERS_PER_VOLUME = 90

_CN_MAP = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100, '千': 1000}
_CN_DIGITS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']

_CH_NUM_RE = re.compile(r'第([一二三四五六七八九十百千零\d]+)章')


def _cn_to_int(s):
    """中文数字转整数。"""
    if s.isdigit():
        return int(s)
    result = 0
    temp = 0
    for ch in s:
        if ch not in _CN_MAP:
            continue
        v = _CN_MAP[ch]
        if v >= 10:
            if temp == 0:
                temp = 1
            result += temp * v
            temp = 0
        else:
            temp = v
    result += temp
    return result


def _int_to_cn(n):
    """整数（0-9999）转中文数字。"""
    if n < 10:
        return _CN_DIGITS[n]

    result = ''
    need_zero = False

    thousands = n // 1000
    if thousands:
        result += _CN_DIGITS[thousands] + '千'
        n %= 1000

    hundreds = n // 100
    if hundreds:
        result += _CN_DIGITS[hundreds] + '百'
        n %= 100
    elif result:
        need_zero = True

    tens = n // 10
    if tens:
        if need_zero:
            result += '零'
            need_zero = False
        if tens == 1 and not result:
            result += '十'
        else:
            result += _CN_DIGITS[tens] + '十'
        n %= 10
    elif result and n > 0:
        need_zero = True

    if n > 0:
        if need_zero:
            result += '零'
        result += _CN_DIGITS[n]

    return result


def _extract_novel_chapter_num(title):
    """从章节标题中提取小说章节编号。返回整数，提取失败返回 None。"""
    m = _CH_NUM_RE.search(title)
    if m:
        return _cn_to_int(m.group(1))
    return None


def _fix_chapter_numbering(groups):
    """校正每卷内的章节编号：如果编号比"上一章编号+1"偏差过大（>=50），自动修正。"""
    fixed_total = 0
    for vi, g in enumerate(groups):
        vol_chapters = g["chapters"]
        if not vol_chapters:
            continue

        last_valid = None
        fixed = 0

        for ci, ch in enumerate(vol_chapters):
            nn = _extract_novel_chapter_num(ch["title"])
            if nn is None:
                continue

            if last_valid is None:
                last_valid = nn
                continue

            expected = last_valid + 1
            if abs(nn - expected) >= 50:
                corrected = _int_to_cn(expected)
                old_title = ch["title"]
                new_title = _CH_NUM_RE.sub(
                    lambda m: f'第{corrected}章',
                    old_title, count=1,
                )
                ch["title"] = new_title
                fixed += 1
                fixed_total += 1
                print(f"    修正卷{vi+1} ci={ci}: {old_title[:25]:25s} → {new_title[:25]}")
                last_valid = expected
            else:
                last_valid = nn

        if fixed:
            print(f"  卷{vi+1} 修正了 {fixed} 个章节编号")

    if fixed_total:
        print(f"  共修正 {fixed_total} 个章节编号")
    return fixed_total
