"use client";

import { useCallback } from "react";
import { messages } from "../../../messages";
import { ReferralDetails } from "../../../page";

export default function ReferralStatisticsRoute({ params }) {
  const t = useCallback((key) => messages.en[key] || key, []);
  return <ReferralDetails id={Number(params.referralId)} locale="en" t={t} onBack={() => window.history.back()} />;
}
