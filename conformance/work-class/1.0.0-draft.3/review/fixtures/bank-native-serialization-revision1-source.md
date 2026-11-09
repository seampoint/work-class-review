# Bank native serialization facts

Revision 1, October 8, 2026. This fictional source addendum supplies explicit records for the single-report XML branch selected by bank source revision 2. It preserves the original case facts. The added names, addresses, tax identifiers, regulatory identifier, contact and classification below are synthetic fixture values. They identify no real bank, taxpayer, customer or filing account. The apparatus must never transmit this file to FinCEN or a real customer.

## 01. Attributed fixture records

Institution Directory MRB-INSTITUTION-01 revision 1 identifies Maple Research Bank, bank MRB-US-01, as a U.S. depository institution with primary regulator FDIC. Its illustrative EIN is 123456789 and RSSD identifier is 1234567. Its fixture address is 100 Example Plaza, Boston, MA 02110, US. Its fixture contact phone is 2025550100. The bank is the transmitter, filing institution, institution where activity occurred and institution holding account account-074. No branch participated. Its transmitter control code is TBSATEST. This is a published test code used only in offline fixture bytes; no test-system submission is authorized.

Contact Directory MRB-CONTACT-01 revision 1 names Example Filing Contact as transmitter contact and MRB Reporting Office as designated contact office. The designated office uses the institution contact phone. No law-enforcement contact has occurred in this selected branch.

Customer Due Diligence Record MRB-CDD-074 revision 4 identifies customer-074 as the fictional entity Maple Example Trading LLC, with illustrative EIN 987654321 and address 200 Example Avenue, Chicago, IL 60601, US. The subject is the sender of the three already recorded transfers. Its customer relationship and account remain active. A non-tax identification document, business occupation, telephone, email, website and alternative name are not supplied in this fixture. The form-of-identification unknown indicator applies; missing optional values remain omitted. Entity status makes individual first name, birth date and gender inapplicable. No confession, termination, suspension, account closure or loss to the bank is established.

Reporting Decision MRB-DECISION-074 revision 1 selects the Other suspicious activities category, with the exact description `Unresolved business purpose of outgoing transfers`. This is a selected fictional Officer judgment. It establishes no criminal finding or intent. The period, dates, combined USD84,000 amount and transaction identities remain those of the original bank source. Individual amounts and counterparty identities remain absent. The report narrative records those absences instead of manufacturing values.

## 02. Complete selected native branch

The initial package contains one SAR activity, six activity-level parties and one nested account-holding institution party. It includes the subject's active account account-074, the known aggregate amount, reporting-period endpoints, one classification, the deposit-account and funds-transfer asset categories, and one narrative segment. It contains no attachment, cyber indicator, IP address, market, commodity, CUSIP or branch record. The reporting-support manifest stays internal and is not an attachment.

The serializer selects the exact field order and scalar restrictions in the retained FinCEN SAR XML schema. It emits UTF-8 XML with a declaration and the fc2 namespace prefix, without subsequent normalization. Sequence identifiers are unique positive integers assigned in document order. The batch PartyCount counts subject parties only and is one; the complete document contains seven Party elements, including the account-holding institution. Activity count is one; attachment counts are zero; total amount is 84000. The filing date for the initial format specimen is October 6, 2026. The filing-institution note is TEST because the fixture uses the test transmitter code.

The corrected/amended format specimen selects a new full package, a correct/amend indicator, October 6 filing date and synthetic prior BSA Identifier 31000000000001. It retains the complete original selected information and adds an explicit correction sentence. It does not substitute an amendment for an uncertain initial filing or reuse the initial approval. Its illustrative eventual BSA Identifier is 31000000000002; actual controlled receipt generation remains separate.

## 03. Correspondence and limits

Every emitted value must identify its source record or declared serializer rule in the field correspondence. Every omitted conditional family must retain its applicability decision. Unknown indicators must not coexist with invented replacement values. The chosen branch must pass the unmodified official schema with a closed local resolver and independent count, sequence, type/indicator and full-package checks. Missing applicable values, extra transmissions and changes after assessment require a new exact package.

Schema admission checks XML structure and scalar restrictions. It does not establish provider acceptance, accurate investigation, adequate suspicion, a correct narrative, complete known information or lawful filing. The filing instructions and this selected branch still require bank review. Primary references are the April 2026 SAR XML guide, version 1.7, and the exact retained official schema dependency set. No real filing interface is exercised.

Not checked: real institution/customer records, test or live account access, FinCEN acceptance, bank compliance approval, legal timeliness or industry review.
