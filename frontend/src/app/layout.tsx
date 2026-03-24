import type { Metadata } from 'next';
import { Geist, Geist_Mono, Manrope, Inter } from 'next/font/google';
import './globals.css';
import { AppHeader } from '@/components/global-nav/AppHeader';

const geistSans = Geist({
    variable: '--font-geist-sans',
    subsets: ['latin'],
});

const geistMono = Geist_Mono({
    variable: '--font-geist-mono',
    subsets: ['latin'],
});

const manrope = Manrope({
    variable: '--font-manrope',
    subsets: ['latin'],
    weight: ['400', '600', '700', '800'],
});

const inter = Inter({
    variable: '--font-inter',
    subsets: ['latin'],
    weight: ['400', '500', '600'],
});

export const metadata: Metadata = {
    title: 'FinanceAI Lab',
    description: 'Neuro-symbolic valuation workspace and observability console.',
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en">
            <body
                className={`${geistSans.variable} ${geistMono.variable} ${manrope.variable} ${inter.variable} antialiased`}
            >
                <AppHeader />
                {children}
            </body>
        </html>
    );
}
