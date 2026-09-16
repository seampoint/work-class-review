# Questions about the review candidate

Applies to Work-Class Governance Specification `1.0.0-draft.2`. This FAQ is explanatory; it does not change the specification.

## What can I evaluate today?

The candidate defines how a system decides whether an action has authority, fits within shared limits, and has enough evidence to let dependent work proceed. Reviewers can examine whether those rules express useful requirements, produce consistent decisions, and cover the cases they would encounter.

The repository includes four worked examples, 425 conformance cases, and reference implementations in TypeScript and Python. Reviewers can inspect the expected decisions and the code that produces them. Both implementations produce the same results on the frozen test suite; that agreement does not establish that every rule is correct or every relevant case is covered. The [reviewer packet](conformance/work-class/1.0.0-draft.2/review/REVIEWER-PACKET-20260914.md) describes the evidence and known gaps.

## Is this a complete authoring system or production runtime?

No. The specification defines a portable contract that different authoring tools and runtime systems can use. Turning an organization's policy into a contract, and connecting that contract to operational systems, require separate tools and integration work. A conforming implementation does not require a Seampoint product.

The host must supply authentic identities and evidence, preserve state and decision records, and control dispatch to external systems. The reference host demonstrates coordination within one process. Its tests do not establish durable crash recovery or production operation. Those properties need to be demonstrated in the host that supplies them. The [scope](Scope.md), [host obligations](library/work-class-specification/1.0.0-draft.2/EXTERNAL-DEPENDENCIES.md), and [license guide](LICENSE.md) describe these boundaries.

## What happens when an outcome is uncertain or evidence conflicts?

An uncertain outcome keeps its reserved capacity. Qualifying effect evidence can settle the reservation; release requires affirmative no-effect evidence and separate authorization. A timeout alone does neither. A dispute blocks affected budget capacity and work that depends on the disputed evidence; unrelated work can remain eligible.

Draft 2 has no operation for clearing a dispute. Affected work can therefore remain blocked indefinitely, even when later evidence would support a resolution. This is a practical limitation of the candidate. Dispute clearance is an identified area for a later draft; it is not available in the current one.

## Why does the specification require human review?

In any governance scheme, people remain responsible for deciding whether a policy is adequate for its declared scope and whether the system represents it faithfully. Known assumptions and gaps need to be visible in that judgment.

The specification makes this responsibility explicit through recorded reviews and decisions tied to the policy and work class. An attestation records accountable judgment; it does not prove that judgment correct. The aim is to make the basis for acceptance inspectable. Whether the process helps people meet that responsibility with reasonable effort remains to be established.

## Have people validated the authoring and review process?

The four worked examples use synthetic review acts, not approvals performed by the people whose roles they represent. They show how policy requirements and review evidence can be represented and evaluated. They do not establish that people can reliably author the contracts, recognize omissions, or judge their fitness for use.

Human exercises and independent implementations would provide further evidence. Reviewing the current candidate does not require either: a concrete ambiguity, missing case, or impractical requirement in one example is useful feedback. The [review guidelines](CONTRIBUTING.md) explain how to report it.
