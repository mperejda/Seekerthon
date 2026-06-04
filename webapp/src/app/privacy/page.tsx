export default function PrivacyPolicyPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Privacy Policy</h1>
      <p className="text-sm text-gray-500 mb-10">Effective date: June 4, 2025</p>

      <div className="space-y-8 text-gray-700 leading-relaxed">
        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">1. Overview</h2>
          <p>
            Seekerthon (&ldquo;we,&rdquo; &ldquo;us,&rdquo; or &ldquo;our&rdquo;) is a hackathon platform built on the Solana
            blockchain. This Privacy Policy explains how we collect, use, and protect information
            when you use the Seekerthon web app or Android app (collectively, the &ldquo;App&rdquo;).
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">2. Information We Collect</h2>

          <h3 className="font-semibold text-gray-800 mt-4 mb-2">Information you provide</h3>
          <ul className="list-disc ml-6 space-y-1">
            <li>Hackathon titles and descriptions (if you create a hackathon)</li>
            <li>Project names, descriptions, and links (if you submit a project)</li>
          </ul>

          <h3 className="font-semibold text-gray-800 mt-4 mb-2">Wallet information</h3>
          <p>
            When you connect a Solana wallet, we read your public wallet address. We do not have
            access to your private keys at any time. Your wallet address is used to identify you
            within the App, record your votes, and attribute hackathon winnings.
          </p>

          <h3 className="font-semibold text-gray-800 mt-4 mb-2">Automatically collected information</h3>
          <ul className="list-disc ml-6 space-y-1">
            <li>Basic usage logs (page views, errors) for debugging purposes</li>
            <li>Device type and operating system (Android app only)</li>
          </ul>

          <h3 className="font-semibold text-gray-800 mt-4 mb-2">Blockchain data</h3>
          <p>
            Transactions you perform (creating hackathons, distributing prizes) are recorded
            permanently on the Solana blockchain and are publicly visible to anyone. This is
            inherent to how blockchain technology works and is outside our control.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">3. How We Use Your Information</h2>
          <p>We use the information we collect to:</p>
          <ul className="list-disc ml-6 mt-2 space-y-1">
            <li>Operate the App and provide its features</li>
            <li>Display hackathons, projects, and voting results</li>
            <li>Associate wallet addresses with votes and project submissions</li>
            <li>Debug and improve the App</li>
          </ul>
          <p className="mt-3">
            We do not sell, rent, or share your personal information with third parties for
            marketing purposes.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">4. Data Storage</h2>
          <p>
            Project and hackathon data you submit is stored in our backend database hosted on
            Railway. Wallet addresses associated with your activity are stored to power the App&rsquo;s
            features. We retain this data for as long as necessary to operate the App.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">5. Third-Party Services</h2>
          <p>The App integrates with the following third-party services:</p>
          <ul className="list-disc ml-6 mt-2 space-y-1">
            <li><strong>Solana blockchain</strong> — for on-chain transactions and escrow</li>
            <li><strong>Mobile Wallet Adapter</strong> — for connecting your Solana wallet on Android</li>
            <li><strong>Railway</strong> — backend hosting</li>
          </ul>
          <p className="mt-3">
            These services have their own privacy policies. We are not responsible for their
            data practices.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">6. Data Security</h2>
          <p>
            We take reasonable measures to protect information stored in our systems. However, no
            Internet transmission is completely secure. The App&rsquo;s smart contracts have not been
            formally audited; funds are actively being raised for a security audit. Use the App
            at your own risk.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">7. Children&rsquo;s Privacy</h2>
          <p>
            The App is not directed at children under 18 years of age. We do not knowingly collect
            personal information from children. If you believe a child has provided us with personal
            information, please contact us and we will delete it.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">8. Your Rights</h2>
          <p>
            You may request deletion of the non-blockchain data we hold about you (such as project
            submissions or hackathon listings) by contacting us. Note that data recorded on the
            Solana blockchain cannot be deleted, as it is permanent by nature.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">9. Changes to This Policy</h2>
          <p>
            We may update this Privacy Policy from time to time. We will indicate the effective
            date at the top of the page. Continued use of the App after changes constitutes
            acceptance of the updated policy.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">10. Contact Us</h2>
          <p>
            If you have questions or concerns about this Privacy Policy, contact us at{" "}
            <a href="mailto:matt.perejda@gmail.com" className="text-purple-600 hover:underline">
              matt.perejda@gmail.com
            </a>.
          </p>
        </section>
      </div>
    </div>
  );
}
