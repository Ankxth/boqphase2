import { createContext, useContext } from "react";

export const DEFAULT_COMPANY_ID = "provident";

interface CompanyContextValue {
  companyId: string;
  setCompanyId: (id: string) => void;
}

export const CompanyContext = createContext<CompanyContextValue>({
  companyId: DEFAULT_COMPANY_ID,
  setCompanyId: () => {},
});

export function useCompany(): CompanyContextValue {
  return useContext(CompanyContext);
}
