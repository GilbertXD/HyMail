import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "../components/AppLayout";
import { AccountSetupPage } from "../features/account/AccountSetupPage";
import { MailPage } from "../features/mail/MailPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/mail" replace />} />
        <Route path="/setup" element={<AccountSetupPage />} />
        <Route path="/mail" element={<MailPage />} />
      </Route>
    </Routes>
  );
}