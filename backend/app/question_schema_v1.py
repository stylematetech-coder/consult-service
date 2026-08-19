"""v1 題目 schema：轉譯自 clarify-req/ 原型的 buildSteps() 邏輯。

每個 step 可帶 showIf（決定何時出現）與 optionsBySource（選項依前一題答案動態決定）。
規則引擎見前端 src/lib/engine.ts，兩邊邏輯需保持一致。
"""

HAIR_LEN_SERVICES = ["dye", "perm", "cut", "haircare"]  # 髮長只在染/燙/剪/護髮需要問，接髮跟頭皮護理不算

SCHEMA_V1 = {
    "version": "v1",
    "steps": [
        {
            "id": "services",
            "type": "multi",
            "question": "請勾選今日想諮詢的服務項目",
            "sub": "可複選",
            "summaryLabel": "服務項目",
            "options": [
                # 接髮目前僅提供男性顧客；性別在填寫一開始就先收集（見 responses.gender），
                # 這裡用 option 層級的 showIf 依性別篩掉選項。
                {"value": "extension", "label": "接髮", "showIf": {"field": "gender", "eq": "male"}},
                {"value": "dye", "label": "染髮"},
                {"value": "perm", "label": "燙髮"},
                {"value": "scalpcare", "label": "頭皮護理"},
                {"value": "haircare", "label": "護髮"},
                {"value": "cut", "label": "剪髮"},
            ],
        },
        # 燙髮：燙捲／縮毛（可複選）挪到共用題（髮長、漂髮經驗）之前，一選完服務項目就先問。
        # 只選縮毛的話，直接視為要做縮毛矯正，不需要再問自然捲跟後面那題「是否需要進行縮毛矯正」；
        # 選了燙捲（不論是否同時選縮毛）才要走原本自然捲 -> 縮毛矯正的判斷流程（見下方 p1/p2）。
        {
            "id": "p0",
            "type": "multi",
            "question": "您想燙捲還是進行縮毛矯正？",
            "sub": "可複選",
            "summaryLabel": "燙髮類型",
            "options": [
                {"value": "curl", "label": "燙捲"},
                {"value": "straight", "label": "縮毛矯正"},
                {"value": "onsite", "label": "待現場評估"},
            ],
            "showIf": {"field": "services", "includes": "perm"},
        },
        {
            "id": "hairLen",
            "type": "single",
            "question": "您目前的髮長是？",
            "summaryLabel": "髮長",
            "options": [
                {"value": "short", "label": "短髮（肩上）"},
                {"value": "medium", "label": "中長髮（及肩～鎖骨）"},
                {"value": "long", "label": "長髮（鎖骨以下）"},
            ],
            "showIf": {"anyOf": [{"field": "services", "includes": s} for s in HAIR_LEN_SERVICES]},
        },
        # 染／燙共用：這兩邊原本都各問一次「一年內是否有漂髮經驗」，合併成一題只問一次，
        # 避免同時選染髮＋燙髮時被重複詢問。護髮不問這題（改成髮況裡的「長期染燙」勾選項）。
        {
            "id": "bleachHistory",
            "type": "single",
            "question": "一年內是否有漂髮經驗？",
            "summaryLabel": "漂髮經驗",
            "options": [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}],
            "showIf": {
                "anyOf": [
                    {"field": "services", "includes": "dye"},
                    {"field": "services", "includes": "perm"},
                ]
            },
        },
        # 燙髮
        {
            "id": "p1",
            "type": "single",
            "question": "您是否有自然捲？",
            "summaryLabel": "自然捲",
            "options": [{"value": "yes", "label": "有自然捲"}, {"value": "no", "label": "無自然捲"}],
            # p0 同時選了燙捲＋縮毛矯正的話，縮毛矯正已經確定要做了，不用再問自然捲來判斷。
            # 只有「只選燙捲、沒選縮毛矯正」時才需要問自然捲，藉此決定要不要問後面的 p2。
            "showIf": {
                "allOf": [
                    {"field": "services", "includes": "perm"},
                    {"field": "p0", "includes": "curl"},
                    {"not": {"field": "p0", "includes": "straight"}},
                ]
            },
        },
        {
            "id": "p2",
            "type": "single",
            "question": "是否需要進行縮毛矯正？",
            "summaryLabel": "縮毛矯正",
            # note 只是顯示給顧客看的提醒文字，不影響作答，最終還是由顧客自己選是或否。
            # \n 是刻意的分行排版，前端 .question-note 有設 white-space: pre-line 才會生效。
            "note": "因為有自然捲，設計師建議搭配進行縮毛矯正，是否要做仍由您決定。\n\n搭配燙髮，縮毛費用+1000",
            "options": [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}],
            # p0 已經選過「縮毛矯正」的話，代表顧客一開始就確定要做了，這裡不用再問一次。
            "showIf": {
                "allOf": [
                    {"field": "services", "includes": "perm"},
                    {"field": "p1", "eq": "yes"},
                    {"not": {"field": "p0", "includes": "straight"}},
                ]
            },
        },
        {
            "id": "p3",
            "type": "single",
            "question": "一年內是否燙過髮？",
            "summaryLabel": "一年內燙髮",
            "options": [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}],
            "showIf": {"field": "services", "includes": "perm"},
        },
        # 接髮
        {
            "id": "e1",
            "type": "single",
            "question": "請問您的禿頭類型是？",
            "summaryLabel": "禿頭類型",
            "options": [
                {"value": "crown", "label": "地中海/頂部稀疏"},
                {"value": "m", "label": "M型禿/髮際線高"},
            ],
            "showIf": {"field": "services", "includes": "extension"},
        },
        {
            # 接髮技術由設計師依禿頭類型判斷，不是顧客要作答的題目，
            # type 為 info：不會出現在顧客的逐題流程裡，只在摘要/明細顯示候選技術供設計師參考。
            "id": "e2",
            "type": "info",
            "question": "依禿頭類型，可參考的接髮技術（設計師參考用，非顧客選項）",
            "summaryLabel": "接髮技術建議（設計師參考）",
            "showIf": {"field": "services", "includes": "extension"},
            "optionsBySource": {
                "source": "e1",
                "map": {
                    "m": [
                        {"value": "hairline", "label": "髮際線加密接髮"},
                        {"value": "bang", "label": "瀏海區域接髮"},
                        {"value": "side", "label": "單邊加密接髮"},
                    ],
                    "crown": [
                        {"value": "crownPatch", "label": "頭頂分區接髮"},
                        {"value": "crownWeave", "label": "頭頂編織接髮"},
                        {"value": "crownVolume", "label": "頭頂增量髮片"},
                    ],
                },
                "default": [{"value": "general", "label": "一般接髮諮詢"}],
            },
        },
        # 染髮
        {
            "id": "d1",
            "type": "single",
            "question": "一年內是否染過黑髮？",
            "summaryLabel": "一年內染黑",
            "options": [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}],
            "showIf": {"field": "services", "includes": "dye"},
        },
        {
            "id": "d2",
            "type": "single",
            "question": "一年內是否使用過開架式染髮染膏？",
            "summaryLabel": "開架染膏使用",
            "options": [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}],
            "showIf": {"field": "services", "includes": "dye"},
        },
        # 顏色深淺（淺/中/深）題已移除：顧客描述預期顏色的文字裡設計師就能判斷色系，不用額外問。
        {
            "id": "d5",
            "type": "text",
            "question": "請描述您預期的顏色",
            "summaryLabel": "預期顏色",
            "placeholder": "例如：奶茶棕、霧感灰、酒紅色…",
            # note 只是顯示給顧客看的提醒文字，不影響作答。
            "note": "預期顏色僅供設計師參考，實際狀況仍依現場判斷，可能會增加其他項目費用，EX:漂髮。",
            "showIf": {"field": "services", "includes": "dye"},
        },
        # 頭皮護理
        {
            "id": "sc1",
            "type": "multi",
            "question": "請問您的頭皮狀況？",
            "sub": "可複選",
            "summaryLabel": "頭皮狀況",
            "options": [
                {"value": "redness", "label": "紅腫"},
                {"value": "oily", "label": "易出油"},
                {"value": "flaky", "label": "易掉屑"},
                {"value": "other", "label": "其他"},
            ],
            # 選了「其他」時前端會多顯示一個文字框，答案存在 answers['sc1Other']
            "otherValue": "other",
            "showIf": {"field": "services", "includes": "scalpcare"},
        },
        # 護髮
        {
            "id": "hc1",
            "type": "multi",
            "question": "請問您的髮況？",
            "sub": "可複選",
            "summaryLabel": "髮況",
            "options": [
                {"value": "frizzy", "label": "毛躁"},
                {"value": "splitEnds", "label": "分岔"},
                {"value": "longTermDyePerm", "label": "長期染燙"},
                {"value": "dyePermCountUnder5", "label": "染燙次數<5"},
                {"value": "longTermMaintenance", "label": "長期保養頭髮"},
                {"value": "other", "label": "其他"},
            ],
            "otherValue": "other",
            "showIf": {"field": "services", "includes": "haircare"},
        },
        # 剪髮
        {
            "id": "c1",
            "type": "textarea",
            "question": "造型需求",
            "sub": "非必要，可留空",
            "summaryLabel": "造型需求",
            "placeholder": "請描述您想要的造型（可留空）",
            "showIf": {"field": "services", "includes": "cut"},
        },
    ],
}
