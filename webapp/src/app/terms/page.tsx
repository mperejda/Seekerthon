export default function TermsOfUsePage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Terms of Use</h1>
      <p className="text-sm text-gray-500 mb-10">Effective date: June 4, 2025</p>

      <div className="space-y-8 text-gray-700 leading-relaxed">
        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">1. Acceptance of Terms</h2>
          <p>
            By accessing or using Seekerthon (the &ldquo;App&rdquo;), you agree to be bound by these Terms of Use.
            If you do not agree to these terms, do not use the App. Seekerthon is a hackathon platform
            built on the Solana blockchain that allows organizers to create hackathons with USDC prize
            pools and allows participants to submit projects and vote.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">2. Eligibility</h2>
          <p>
            You must be at least 18 years of age to use Seekerthon. By using the App, you represent
            and warrant that you meet this requirement and that your use of the App does not violate
            any applicable laws or regulations in your jurisdiction.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">3. Blockchain Transactions</h2>
          <p>
            Seekerthon uses the Solana blockchain for escrow of prize funds and distribution of
            rewards. All on-chain transactions are irreversible once confirmed. You are solely
            responsible for ensuring the accuracy of wallet addresses and transaction details before
            signing. Seekerthon is not responsible for any loss of funds resulting from user error,
            wallet compromise, or network issues.
          </p>
          <p className="mt-3">
            The App has not been formally security audited. Funds are actively being raised to
            conduct a professional security audit. Use the App at your own risk and do not deposit
            funds you cannot afford to lose.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">4. Hackathon Organizers</h2>
          <p>
            Organizers who create hackathons are responsible for ensuring their hackathons comply
            with all applicable laws. Prize funds are held in a smart contract escrow on Solana.
            Organizers acknowledge that once funds are deposited into escrow, distribution is
            governed by the smart contract and the outcome of participant voting.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">5. Project Submissions</h2>
          <p>
            By submitting a project, you represent that you have the right to share the content and
            that it does not infringe any third-party intellectual property rights. Seekerthon does
            not claim ownership of submitted content. You retain all rights to your work.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">6. Prohibited Conduct</h2>
          <p>You agree not to:</p>
          <ul className="list-disc ml-6 mt-2 space-y-1">
            <li>Manipulate votes or exploit the voting system</li>
            <li>Submit false, misleading, or plagiarized project content</li>
            <li>Attempt to compromise the security of the App or its smart contracts</li>
            <li>Use the App for any unlawful purpose</li>
            <li>Impersonate any person or entity</li>
          </ul>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">7. Disclaimer of Warranties</h2>
          <p>
            The App is provided &ldquo;as is&rdquo; without warranty of any kind. Seekerthon does not warrant
            that the App will be uninterrupted, error-free, or free of security vulnerabilities.
            We disclaim all warranties, express or implied, including but not limited to warranties
            of merchantability, fitness for a particular purpose, and non-infringement.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">8. Limitation of Liability</h2>
          <p>
            To the maximum extent permitted by law, Seekerthon and its operators shall not be liable
            for any indirect, incidental, special, consequential, or punitive damages, including loss
            of funds, arising from your use of or inability to use the App.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">9. Changes to Terms</h2>
          <p>
            We may update these Terms of Use from time to time. Continued use of the App after
            changes constitutes acceptance of the revised terms.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">10. Contact</h2>
          <p>
            For questions about these Terms, contact us at{" "}
            <a href="mailto:matt.perejda@gmail.com" className="text-purple-600 hover:underline">
              matt.perejda@gmail.com
            </a>.
          </p>
        </section>
      </div>
    </div>
  );
}
