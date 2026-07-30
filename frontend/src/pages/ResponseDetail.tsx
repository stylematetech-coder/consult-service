import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type QuestionnaireSchema, type ResponseRecord } from "../api/client";
import { computeVisibleSteps, formatAnswer } from "../lib/engine";

export function ResponseDetail() {
  const { id } = useParams<{ id: string }>();
  const [response, setResponse] = useState<ResponseRecord | null>(null);
  const [schema, setSchema] = useState<QuestionnaireSchema | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api
      .getResponse(id)
      .then(async (res) => {
        setResponse(res.response);
        const schemaRes = await api.getSchema(res.response.schema_id);
        setSchema(schemaRes.schema);
      })
      .catch(() => setError("找不到這筆問卷紀錄"));
  }, [id]);

  if (error) {
    return (
      <div className="page">
        <div className="card error-text">{error}</div>
      </div>
    );
  }

  if (!response || !schema) {
    return (
      <div className="page">
        <div className="card">載入中…</div>
      </div>
    );
  }

  // gender 是填寫一開始就收集的核心欄位（見 responses.gender），不是 schema 裡的一道題，
  // 但規則引擎判斷「接髮」選項要不要出現時仍需要 answers.gender，所以這裡補回去。
  const answersWithGender = { ...response.answers, gender: response.gender };
  const visibleSteps = computeVisibleSteps(schema.steps, answersWithGender);

  return (
    <div className="page">
      <div className="card">
        <Link to="/lookup">&larr; 返回查詢</Link>
        <div className="title" style={{ marginTop: 12 }}>
          {response.name}
          <span className={`status-badge status-${response.status}`}>
            {response.status === "submitted" ? "已送出" : "填寫中"}
          </span>
        </div>
        <div className="subtitle">
          {response.phone} ・ {response.gender === "male" ? "男生" : "女生"} ・ 填寫於 {response.created_at}
          {response.submitted_at ? `・送出於 ${response.submitted_at}` : ""}
        </div>
        <div className="summary-list">
          {visibleSteps.map((step) => (
            <div className="summary-item" key={step.id}>
              <div className="summary-label">{step.summaryLabel ?? step.question}</div>
              <div className="summary-answer">{formatAnswer(step, answersWithGender)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
