# HanaV 공통 이메일 승인 인증 도입 가이드

## 범위 및 보안 원칙

| 코드 | 앱 | GitHub 저장소 |
|---|---|---|
| `stock-analyzer` | Stock Analyzer | stock-analyzer |
| `hanav-trading` | HanaV Trading | hanavtrading-khahn |
| `corporate-finder` | Corporate Finder | corporate_finder-khahn |
| `pension-tax` | Pension Tax Lab | pension_tax-khahn |
| `private-portfolio` | Private Portfolio | private-portfolio-khahn |

ETF Finder는 기존 Streamlit Private 앱이므로 **Sharing 이메일 허용** 방식을 유지합니다.
Superpapa JARVIS는 가족용 음성 비서로 이번 금융앱 인증 대상이 아닙니다.

공개 웹앱의 URL 자체는 외부에서 접근할 수 있지만, **강제(enforced) 모드**에서는
서버가 Supabase Auth의 이메일 신원과 중앙 DB 접근 허용 상태를 확인하기 전까지
앱 화면 및 기존 비밀번호 단계에 들어갈 수 없습니다.

## 1. 중앙 승인 DB 테이블

HanaV-Finder **실제 Supabase 프로젝트**의 SQL Editor에서
[중앙 승인 테이블 SQL](../sql/hanav_app_access.sql)을 실행하세요.

이 SQL은 새 테이블 `public.hanav_app_access`만 추가합니다.
기존 ETF/법인/Stock Analyzer DB를 지우지 않습니다.

**행 컬럼**: `email`(소문자 실제 이메일), `app_code`(위 코드 또는 `all`),
`enabled`(true/false). `all`은 다섯 앱 공통 허용을 뜻합니다.
특정 앱 `enabled=false` 행은 `all=true`보다 우선합니다.
외부 사용자는 RLS를 통해 **자신의 승인 상태만 조회**하며, 수정 권한이 없습니다.

### 관리자용 SQL 예시 (이메일은 반드시 직접 수정)

```sql
-- 모든 금융 웹앱 허용 (한 줄의 승인)
INSERT INTO public.hanav_app_access(email, app_code, enabled)
VALUES ('owner@example.com', 'all', true)
ON CONFLICT (email, app_code)
DO UPDATE SET enabled=excluded.enabled, updated_at=now();

-- Stock Analyzer만 허용
INSERT INTO public.hanav_app_access(email, app_code, enabled)
VALUES ('colleague@example.com', 'stock-analyzer', true)
ON CONFLICT (email, app_code)
DO UPDATE SET enabled=excluded.enabled, updated_at=now();

-- 승인 전부 철회 (다음 페이지 실행부터 접근 차단)
DELETE FROM public.hanav_app_access WHERE email='colleague@example.com';
```

**주의:** SQL 수정은 프로젝트 관리자만 실행해야 합니다.

## 2. Supabase Auth 이메일 인증 준비

1. `Authentication → Users`에서 **본인 계정을 우선** 생성 또는 초대합니다.
   서버 코드는 `create_user=false`이므로 인증번호를 요청해도
   미등록 계정이 저절로 생성되지 않습니다.
2. `Authentication → Providers → Email`에서 이메일 로그인을 활성화합니다.
3. `Authentication → Email Templates → Magic Link/OTP`의 내용을
   `<p>HanaV 로그인 인증번호: <strong>{{ .Token }}</strong></p>`처럼
   **숫자 OTP가 보이도록** 설정합니다. 초대 또는 가입확인 메일 템플릿도 점검합니다.
4. Supabase 기본 메일 서버는 **해당 프로젝트 팀 구성원에게만 메일 발송**,
   **시간당 2건**이므로 일반 직원 이메일을 사용하려면
   `Authentication → SMTP Settings`에서 Resend·SendGrid·Brevo 등
   **사용자 소유 SMTP**를 설정해야 합니다. 실제 작동 여부를 시험하세요.
5. 인증번호로 로그인할 때, Auth 사용자 신원이 확인되고
   `hanav_app_access`에 사용 가능한 승인 행이 있어야만 통과합니다.
   기존 앱별 `APP_PASSWORD`는 **추가로 그대로 요구**됩니다.

공식 문서:
- [Supabase custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp)
- [Supabase OTP 템플릿](https://supabase.com/docs/guides/auth/auth-email-templates)

## 3. Streamlit Cloud Secrets — 5개 앱에 각각 설정

**기존 비밀번호, API 키, Supabase URL 및 DB 비밀을 삭제하지 마세요.**
각 앱의 **Settings → Secrets**에 다음 값이 필요합니다.

```toml
# 모든 코드는 이미 배포할 수 있지만, 아래 모드를 바꾸기 전까지
# 기존 APP_PASSWORD 로그인 방식으로 유지됩니다.
EMAIL_ACCESS_MODE = "legacy"

# Supabase 프로젝트 Settings → Data API의 URL
SUPABASE_URL = "https://<actual-project-ref>.supabase.co"

# Authentication 통신용 공개 anon 키: service_role 키를 사용하면 안 됩니다.
SUPABASE_ANON_KEY = "<actual-SUPABASE_ANON_KEY>"

# APP_PASSWORD = "기존 각 앱 비밀번호"  # 기존 설정 유지
```

별도 관리자 모드가 있는 앱의 `ADMIN_PASSWORD`도 변경하지 않습니다.

### 활성화 절차 (앱마다 하나씩)

1. 중앙 SQL 테이블 생성·정책 확인
2. Supabase Auth 이메일·SMTP 준비
3. 본인 이메일의 Supabase Auth 사용자 생성 + `app_code='all'` 또는 해당 앱 승인 행 생성
4. 대상 Streamlit 앱의 세 가지 Secrets 등록
5. **그 앱에서만** `EMAIL_ACCESS_MODE = "enforced"`로 변경 후 재배포
6. 새 브라우저/시크릿 모드에서 본인 이메일 인증번호 → 기존 앱 비밀번호 통과 확인
7. 허용되지 않은 이메일과 승인 철회 후 접근 거절 테스트
8. 정상 작동하면 나머지 4개 앱도 동일하게 활성화

**중요:** `legacy`가 기본값이며 인증 코드가 배포됐다는 것만으로
이메일 접근 제한이 활성화되는 것은 아닙니다.
필요한 Secrets 또는 DB가 없는 상태에서 `enforced`로 변경하면
관리자도 앱 접근이 막힙니다. 이 경우 Secrets를 `legacy`로
일시 되돌려 설정을 점검할 수 있습니다. **운영 허용을 뜻하지는 않습니다.**

## 4. 직원 접속과 권한 철회

승인된 직원:
**웹앱 URL → 기존 Supabase Auth 계정 이메일 입력 → 인증번호 확인 → 기존 앱 비밀번호 → 앱 사용**.

- 이메일 승인 철회: SQL Editor에서 해당 앱 행을 `enabled=false`로 변경하거나 삭제.
- 전체 승인 철회: 해당 이메일 모든 행 삭제.
- 변경 사항은 다음 Streamlit 페이지 실행 시 적용됩니다. 중단 없이
  열린 기존 브라우저 화면에 이미 표시된 자료를 원격으로 지울 수는 없습니다.
- DB 접속 오류·정책 미설정·Auth 장애에서는 인증을 통과시키지 않습니다.
- 인증 코드는 단순 연락처 확인이 아닌 실제 **Supabase 서버에서 발급한
  access token** 확인 후에만 로그인 처리됩니다.
- 브라우저/세션마다 다시 인증이 필요할 수 있습니다.
- 이메일 OTP 자체를 다른 사람에게 전달하면 위험하므로 전달하지 않도록 안내하세요.

회사 전산·컴플라이언스 정책에 맞춰 직원 배포 전에 승인된 외부 서비스의
데이터 반출 및 API 이용 규정을 점검해야 합니다.

## ETF Finder와의 차이

ETF Finder는 이미 **Streamlit Private Sharing**으로 접속자 범위를 관리합니다.
별도 Supabase Auth로 이중 인증을 만들지 않았으며, 사용자 초대/철회는
기존 Streamlit 관리 화면에서 처리합니다.
